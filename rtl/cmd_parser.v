// cmd_parser.v  -- implements the Dumb-TV UART control protocol (indexed OSD).
//
// Frame:  A5 | CMD | LEN(16 LE) | PAYLOAD | CRC8   (CRC-8/SMBUS, poly 0x07)
//
// Commands:
//   PING(01)        -> ACK
//   GET_INFO(02)    -> INFO(proto,fw,osd_w,osd_h,max_w,max_h,flags)
//   OSD_ENABLE(10)  en(1)
//   OSD_ALPHA(12)   alpha(1)                       master fade
//   OSD_FB_WRITE(20) addr(2) + N index bytes       canvas indices (low nibble)
//   OSD_FB_FILL(21)  addr(2) count(2) index(1)     fill canvas with an index
//   PALETTE_SET(26)  index(1) A(1) R(1) G(1) B(1)  set a palette entry
//
// Writes stream to the canvas / palette as bytes arrive; a bad CRC returns NACK
// so the host re-sends. Out-of-range framebuffer writes are skipped and return
// NACK(ERR_RANGE). See docs/uart-protocol.md.

`default_nettype none

module cmd_parser #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter FB_AW = $clog2(OSD_W*OSD_H),
    parameter N_GLYPHS = 8,
    parameter GW = 4,             // glyph width
    parameter GH = 4,             // glyph height
    parameter TEXT_BASE = 0,      // glyph slot of char code 0 (font base)
    parameter FW_AW = 14          // firmware RAM address width (16 KB)
)(
    input  wire        clk,
    input  wire        rst,
    // from uart_rx
    input  wire [7:0]  rx_data,
    input  wire        rx_valid,
    // to uart_tx
    output reg  [7:0]  tx_data,
    output reg         tx_start,
    input  wire        tx_busy,
    // to ctrl_regs
    output reg  [3:0]  ctrl_addr,
    output reg  [15:0] ctrl_wdata,
    output reg         ctrl_we,
    // to osd_fb (canvas index write port)
    output reg         fb_we,
    output reg [FB_AW-1:0] fb_waddr,
    output reg [3:0]   fb_wdata,
    // to palette write port
    output reg         pal_we,
    output reg [3:0]   pal_waddr,
    output reg [31:0]  pal_wdata,
    // to firmware RAM write port (FW_WRITE)
    output reg         fw_we,
    output reg [FW_AW-1:0] fw_waddr,
    output reg [7:0]   fw_wdata,
    // double-buffer flip handshake (to/from compositor)
    output reg         flip_req,
    input  wire        flip_done,
    // command-mux hooks: rx_ready = can accept a byte this cycle;
    // busy = a frame is in progress (not idle in S_SYNC)
    output wire        rx_ready,
    output wire        busy
);
    // ---- opcodes ----
    localparam OP_PING = 8'h01, OP_INFO  = 8'h02,
               OP_EN   = 8'h10, OP_ALPHA = 8'h12,
               OP_GUP  = 8'h22, OP_GBLIT = 8'h23, OP_TEXT = 8'h24, OP_FRECT = 8'h25,
               OP_FBW  = 8'h20, OP_FBF   = 8'h21, OP_PAL = 8'h26,
               OP_CLEAR = 8'h27, OP_FLIP = 8'h28, OP_MUXSEL = 8'h40,
               OP_BRIGHT = 8'h30, OP_CONTR = 8'h31, OP_BL = 8'h32,
               OP_FWHALT = 8'h50, OP_FW = 8'h51, OP_FWSTART = 8'h52,
               OP_LVDS = 8'h60;
    localparam RSP_ACK = 8'h80, RSP_NACK = 8'h81, RSP_INFO = 8'h82;
    localparam ERR_CRC = 8'h01, ERR_LEN  = 8'h02, ERR_UNK  = 8'h03, ERR_RANGE = 8'h04;
    localparam MAX_TEXT = 32;                        // max DRAW_TEXT string length
    localparam [16:0] FW_DEPTH = (17'd1 << FW_AW);   // firmware RAM size in bytes
    // ---- ctrl_regs addresses ----
    localparam A_EN = 4'd0, A_ALPHA = 4'd1, A_MUX = 4'd2, A_BRIGHT = 4'd3,
               A_CONTR = 4'd4, A_BL = 4'd5, A_CORE = 4'd6, A_LVDS = 4'd7;
    // ---- INFO constants ----
    localparam [15:0] MAX_W = 16'd1920, MAX_H = 16'd1080;
    localparam FW = FB_AW + 1;                       // canvas counter width
    localparam [FW-1:0] FB_DEPTH = OSD_W * OSD_H;
    localparam GPIX = GW * GH;                       // pixels per glyph
    localparam GAW  = $clog2(N_GLYPHS * GPIX);       // glyph-store address width

    // ---- states ----
    localparam S_SYNC=0, S_CMD=1, S_LENL=2, S_LENH=3, S_PAY=4, S_CRC=5,
               S_EXEC=6, S_FILL=7, S_RLOAD=8, S_RWAIT=9, S_FLIPWAIT=10,
               S_BLIT_RD=11, S_BLIT_WR=12, S_FRECT=13;
    reg [3:0] state;

    reg [7:0]  cmd, crc, len_lo;
    reg [15:0] len, pay_idx;
    reg        bad_len;
    reg        range_err;
    reg [7:0]  pbuf [0:15];        // payload buffer for small commands

    // fb-write streaming
    reg [15:0] fb_addr;
    // firmware-write streaming
    reg [16:0] fw_addr;

    // fill engine (also used by CLEAR: full-canvas fill)
    reg [FW-1:0] fill_addr, fill_cnt;
    reg [3:0]    fill_idx;
    reg [7:0]    fill_ackcmd;      // which cmd the fill/clear acks

    // flip handshake (flip_done crosses from the pixel domain)
    reg flip_done_s1, flip_done_s2, flip_done_prev;

    // glyph store + blit engine
    reg          gs_we;
    reg [GAW-1:0] gs_waddr;
    reg [3:0]    gs_wdata;
    wire [3:0]   gs_rdata;
    reg [GAW-1:0] g_up_base;       // slot base for GLYPH_UPLOAD
    reg [GAW-1:0] b_base;          // slot base for GLYPH_BLIT
    reg [15:0]   b_x, b_y;         // blit destination origin
    reg [15:0]   gx, gy;          // glyph pixel counters
    wire [GAW-1:0] gs_raddr = b_base + gy * GW + gx;   // combinational read addr
    // fill-rect engine
    reg [15:0]   fr_x, fr_y, fr_w, fr_h, rx, ry;
    reg [3:0]    fr_idx;
    // draw-text engine (blit a run of glyphs, slot = TEXT_BASE + char)
    reg [7:0]    txt_buf [0:MAX_TEXT-1];
    reg [15:0]   t_x, t_y, t_i, n_chars;
    reg          blit_is_text;

    glyph_store #(.N_GLYPHS(N_GLYPHS), .GW(GW), .GH(GH)) u_glyphs (
        .clk(clk), .we(gs_we), .waddr(gs_waddr), .wdata(gs_wdata),
        .raddr(gs_raddr), .rdata(gs_rdata));

    // response builder
    reg [7:0]  resp [0:15];
    reg [4:0]  resp_total, resp_idx;
    reg [7:0]  resp_crc;

    // ---- CRC-8/SMBUS (poly 0x07, init 0x00) ----
    function [7:0] crc8;
        input [7:0] c_in;
        input [7:0] d;
        integer i;
        reg [7:0] c;
        begin
            c = c_in ^ d;
            for (i = 0; i < 8; i = i + 1)
                c = c[7] ? ((c << 1) ^ 8'h07) : (c << 1);
            crc8 = c;
        end
    endfunction

    // ---- response builders ----
    task build_ack; input [7:0] c; begin
        resp[0]<=8'hA5; resp[1]<=RSP_ACK; resp[2]<=8'd1; resp[3]<=8'd0; resp[4]<=c;
        resp_total<=5'd5; resp_idx<=5'd0; resp_crc<=8'd0;
    end endtask

    task build_nack; input [7:0] c; input [7:0] e; begin
        resp[0]<=8'hA5; resp[1]<=RSP_NACK; resp[2]<=8'd2; resp[3]<=8'd0; resp[4]<=c; resp[5]<=e;
        resp_total<=5'd6; resp_idx<=5'd0; resp_crc<=8'd0;
    end endtask

    task build_info; begin
        resp[0]<=8'hA5; resp[1]<=RSP_INFO; resp[2]<=8'd12; resp[3]<=8'd0;
        resp[4]<=8'd1;                       // protocol version
        resp[5]<=8'd0; resp[6]<=8'd2;        // fw major.minor
        resp[7]<=OSD_W[7:0];  resp[8]<=OSD_W[15:8];
        resp[9]<=OSD_H[7:0];  resp[10]<=OSD_H[15:8];
        resp[11]<=MAX_W[7:0]; resp[12]<=MAX_W[15:8];
        resp[13]<=MAX_H[7:0]; resp[14]<=MAX_H[15:8];
        resp[15]<=8'd0;                      // flags
        resp_total<=5'd16; resp_idx<=5'd0; resp_crc<=8'd0;
    end endtask

    wire [15:0] len_full = {rx_data, len_lo};

    // mux backpressure: the parser only consumes rx_data in the receive states.
    assign rx_ready = (state == S_SYNC) || (state == S_CMD) || (state == S_LENL) ||
                      (state == S_LENH) || (state == S_PAY)  || (state == S_CRC);
    assign busy     = (state != S_SYNC);

    always @(posedge clk) begin
        if (rst) begin
            state    <= S_SYNC;
            tx_start <= 1'b0;
            ctrl_we  <= 1'b0;
            fb_we    <= 1'b0;
            pal_we   <= 1'b0;
            gs_we    <= 1'b0;
            fw_we    <= 1'b0;
            flip_req <= 1'b0;
            {flip_done_s2, flip_done_s1, flip_done_prev} <= 3'b000;
        end else begin
            tx_start <= 1'b0;
            ctrl_we  <= 1'b0;
            fb_we    <= 1'b0;
            pal_we   <= 1'b0;
            gs_we    <= 1'b0;
            fw_we    <= 1'b0;

            // sync flip_done (pixel domain) into this clock
            {flip_done_s2, flip_done_s1} <= {flip_done_s1, flip_done};

            case (state)
                // ---------------- receive framing ----------------
                S_SYNC: if (rx_valid && rx_data == 8'hA5) begin
                    crc <= 8'd0; state <= S_CMD;
                end
                S_CMD: if (rx_valid) begin
                    cmd <= rx_data; crc <= crc8(crc, rx_data); state <= S_LENL;
                end
                S_LENL: if (rx_valid) begin
                    len_lo <= rx_data; crc <= crc8(crc, rx_data); state <= S_LENH;
                end
                S_LENH: if (rx_valid) begin
                    crc       <= crc8(crc, rx_data);
                    len       <= len_full;
                    pay_idx   <= 16'd0;
                    range_err <= 1'b0;
                    case (cmd)
                        OP_PING, OP_INFO, OP_FLIP,
                        OP_FWHALT, OP_FWSTART: bad_len <= (len_full != 16'd0);
                        OP_FW:            bad_len <= (len_full < 16'd3);   // addr + >=1 byte
                        OP_EN, OP_ALPHA:  bad_len <= (len_full != 16'd1);
                        OP_CLEAR:         bad_len <= (len_full > 16'd1);   // 0 or 1 byte
                        OP_FBF, OP_PAL:   bad_len <= (len_full != 16'd5);
                        OP_GBLIT:         bad_len <= (len_full != 16'd5);  // slot x y
                        OP_FRECT:         bad_len <= (len_full != 16'd9);  // x y w h index
                        OP_GUP:           bad_len <= (len_full != (16'd1 + GPIX)); // slot + pixels
                        OP_TEXT:          bad_len <= (len_full < 16'd5);   // x y + >=1 char
                        OP_MUXSEL, OP_BRIGHT, OP_CONTR, OP_BL: bad_len <= (len_full != 16'd1);
                        OP_LVDS:          bad_len <= (len_full != 16'd2);
                        OP_FBW:           bad_len <= (len_full < 16'd3);
                        default:          bad_len <= 1'b0; // unknown -> NACK in EXEC
                    endcase
                    state <= (len_full == 16'd0) ? S_CRC : S_PAY;
                end
                // ---------------- payload ----------------
                S_PAY: if (rx_valid) begin
                    crc <= crc8(crc, rx_data);
                    if (cmd == OP_FBW && !bad_len) begin
                        if (pay_idx == 16'd0)      fb_addr[7:0]  <= rx_data;
                        else if (pay_idx == 16'd1) fb_addr[15:8] <= rx_data;
                        else begin
                            if (fb_addr < FB_DEPTH) begin
                                fb_we    <= 1'b1;
                                fb_waddr <= fb_addr[FB_AW-1:0];
                                fb_wdata <= rx_data[3:0];      // one index per byte
                            end else begin
                                range_err <= 1'b1;
                            end
                            fb_addr <= fb_addr + 1'b1;
                        end
                    end else if (cmd == OP_GUP && !bad_len) begin
                        if (pay_idx == 16'd0) begin            // slot byte
                            if (rx_data < N_GLYPHS) g_up_base <= rx_data * GPIX;
                            else                    range_err <= 1'b1;
                        end else if (!range_err) begin         // one glyph pixel per byte
                            gs_we    <= 1'b1;
                            gs_waddr <= g_up_base + pay_idx[GAW-1:0] - 1'b1;
                            gs_wdata <= rx_data[3:0];
                        end
                    end else if (cmd == OP_TEXT && !bad_len) begin
                        if (pay_idx < 16'd4) pbuf[pay_idx[3:0]] <= rx_data;    // x, y
                        else if ((pay_idx - 16'd4) < MAX_TEXT)
                            txt_buf[pay_idx - 16'd4] <= rx_data;               // string
                    end else if (cmd == OP_FW && !bad_len) begin
                        if (pay_idx == 16'd0)      fw_addr <= {9'b0, rx_data}; // addr lo (clears hi)
                        else if (pay_idx == 16'd1) fw_addr[15:8] <= rx_data;   // addr hi
                        else begin
                            if (fw_addr < FW_DEPTH) begin
                                fw_we    <= 1'b1;
                                fw_waddr <= fw_addr[FW_AW-1:0];
                                fw_wdata <= rx_data;                           // one byte
                            end else begin
                                range_err <= 1'b1;
                            end
                            fw_addr <= fw_addr + 1'b1;
                        end
                    end else begin
                        if (pay_idx < 16'd16) pbuf[pay_idx[3:0]] <= rx_data;
                    end
                    pay_idx <= pay_idx + 1'b1;
                    if (pay_idx == len - 1) state <= S_CRC;
                end
                // ---------------- crc check + dispatch ----------------
                S_CRC: if (rx_valid) begin
                    if (bad_len)              begin build_nack(cmd, ERR_LEN); state <= S_RLOAD; end
                    else if (rx_data != crc)  begin build_nack(cmd, ERR_CRC); state <= S_RLOAD; end
                    else                      state <= S_EXEC;
                end
                S_EXEC: begin
                    case (cmd)
                        OP_PING: begin build_ack(cmd); state <= S_RLOAD; end
                        OP_INFO: begin build_info;     state <= S_RLOAD; end
                        OP_EN: begin
                            ctrl_addr <= A_EN; ctrl_wdata <= {8'd0, pbuf[0]}; ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_ALPHA: begin
                            ctrl_addr <= A_ALPHA; ctrl_wdata <= {8'd0, pbuf[0]}; ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_FBW: begin
                            if (range_err) build_nack(cmd, ERR_RANGE);
                            else           build_ack(cmd);
                            state <= S_RLOAD;
                        end
                        OP_FBF: begin
                            fill_addr   <= {pbuf[1], pbuf[0]};
                            fill_cnt    <= {pbuf[3], pbuf[2]};
                            fill_idx    <= pbuf[4][3:0];
                            fill_ackcmd <= OP_FBF;
                            state <= S_FILL;
                        end
                        OP_CLEAR: begin              // wipe the whole back canvas
                            fill_addr   <= {FW{1'b0}};
                            fill_cnt    <= FB_DEPTH;
                            fill_idx    <= (len != 16'd0) ? pbuf[0][3:0] : 4'd0;
                            fill_ackcmd <= OP_CLEAR;
                            state <= S_FILL;
                        end
                        OP_PAL: begin
                            pal_we    <= 1'b1;
                            pal_waddr <= pbuf[0][3:0];
                            pal_wdata <= {pbuf[1], pbuf[2], pbuf[3], pbuf[4]}; // A,R,G,B
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_FLIP: begin               // request buffer swap at VSync
                            flip_req <= ~flip_req;
                            state <= S_FLIPWAIT;
                        end
                        OP_GUP: begin                // glyph pixels streamed in S_PAY
                            if (range_err) build_nack(cmd, ERR_RANGE);
                            else           build_ack(cmd);
                            state <= S_RLOAD;
                        end
                        OP_GBLIT: begin              // blit glyph `slot` at (x,y)
                            if (pbuf[0] >= N_GLYPHS) begin
                                build_nack(cmd, ERR_RANGE); state <= S_RLOAD;
                            end else begin
                                b_base <= pbuf[0] * GPIX;
                                b_x    <= {pbuf[2], pbuf[1]};
                                b_y    <= {pbuf[4], pbuf[3]};
                                gx <= 16'd0; gy <= 16'd0;
                                blit_is_text <= 1'b0;
                                state <= S_BLIT_RD;
                            end
                        end
                        OP_TEXT: begin               // blit a run of glyphs (font)
                            n_chars <= ((len - 16'd4) > MAX_TEXT) ? MAX_TEXT : (len - 16'd4);
                            t_x <= {pbuf[1], pbuf[0]};
                            t_y <= {pbuf[3], pbuf[2]};
                            t_i <= 16'd0;
                            blit_is_text <= 1'b1;
                            b_base <= (TEXT_BASE + txt_buf[0]) * GPIX;   // first char
                            b_x <= {pbuf[1], pbuf[0]};
                            b_y <= {pbuf[3], pbuf[2]};
                            gx <= 16'd0; gy <= 16'd0;
                            state <= S_BLIT_RD;
                        end
                        OP_MUXSEL: begin             // select input mux
                            ctrl_addr <= A_MUX; ctrl_wdata <= {12'd0, pbuf[0][3:0]};
                            ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_BRIGHT: begin             // picture brightness
                            ctrl_addr <= A_BRIGHT; ctrl_wdata <= {8'd0, pbuf[0]};
                            ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_CONTR: begin              // picture contrast
                            ctrl_addr <= A_CONTR; ctrl_wdata <= {8'd0, pbuf[0]};
                            ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_BL: begin                 // backlight PWM duty
                            ctrl_addr <= A_BL; ctrl_wdata <= {8'd0, pbuf[0]};
                            ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_LVDS: begin               // native-LVDS output mapping
                            ctrl_addr <= A_LVDS; ctrl_wdata <= {pbuf[1], pbuf[0]};
                            ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_FWHALT: begin             // hold the SERV core in reset
                            ctrl_addr <= A_CORE; ctrl_wdata <= 16'd1; ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_FWSTART: begin            // release the core (run firmware)
                            ctrl_addr <= A_CORE; ctrl_wdata <= 16'd0; ctrl_we <= 1'b1;
                            build_ack(cmd); state <= S_RLOAD;
                        end
                        OP_FW: begin                 // firmware bytes streamed in S_PAY
                            if (range_err) build_nack(cmd, ERR_RANGE);
                            else           build_ack(cmd);
                            state <= S_RLOAD;
                        end
                        OP_FRECT: begin             // fill rectangle with an index
                            fr_x   <= {pbuf[1], pbuf[0]};
                            fr_y   <= {pbuf[3], pbuf[2]};
                            fr_w   <= {pbuf[5], pbuf[4]};
                            fr_h   <= {pbuf[7], pbuf[6]};
                            fr_idx <= pbuf[8][3:0];
                            rx <= 16'd0; ry <= 16'd0;
                            state <= S_FRECT;
                        end
                        default: begin build_nack(cmd, ERR_UNK); state <= S_RLOAD; end
                    endcase
                end
                // ---------------- OSD_FB_FILL: write `count` indices ----------------
                S_FILL: begin
                    if (fill_cnt != {FW{1'b0}}) begin
                        if (fill_addr < FB_DEPTH) begin
                            fb_we    <= 1'b1;
                            fb_waddr <= fill_addr[FB_AW-1:0];
                            fb_wdata <= fill_idx;
                        end else begin
                            range_err <= 1'b1;
                        end
                        fill_addr <= fill_addr + 1'b1;
                        fill_cnt  <= fill_cnt - 1'b1;
                    end else begin
                        if (range_err) build_nack(fill_ackcmd, ERR_RANGE);
                        else           build_ack(fill_ackcmd);
                        state <= S_RLOAD;
                    end
                end
                // ---------------- FLIP: wait for the VSync swap, then ACK ----------------
                S_FLIPWAIT: if (flip_done_s2 != flip_done_prev) begin
                    flip_done_prev <= flip_done_s2;
                    build_ack(OP_FLIP);
                    state <= S_RLOAD;
                end
                // ---------------- GLYPH_BLIT: glyph pixels -> back canvas ----------------
                // gs_raddr is combinational from (gy,gx); this state lets the
                // 1-clock glyph-store read settle before S_BLIT_WR uses it.
                S_BLIT_RD: state <= S_BLIT_WR;
                S_BLIT_WR: begin
                    // gs_rdata valid now; write it if opaque and on-canvas (clip)
                    if (gs_rdata != 4'd0 &&
                        (b_x + gx) < OSD_W && (b_y + gy) < OSD_H) begin
                        fb_we    <= 1'b1;
                        fb_waddr <= (b_y + gy) * OSD_W + (b_x + gx);
                        fb_wdata <= gs_rdata;
                    end
                    if (gx == GW-1) begin
                        gx <= 16'd0;
                        if (gy == GH-1) begin
                            if (blit_is_text && (t_i + 16'd1 < n_chars)) begin
                                t_i    <= t_i + 16'd1;                 // next char
                                b_base <= (TEXT_BASE + txt_buf[t_i + 16'd1]) * GPIX;
                                b_x    <= t_x + (t_i + 16'd1) * GW;     // advance x
                                b_y    <= t_y;
                                gy <= 16'd0;
                                state <= S_BLIT_RD;
                            end else begin
                                build_ack(blit_is_text ? OP_TEXT : OP_GBLIT);
                                state <= S_RLOAD;
                            end
                        end else begin gy <= gy + 1'b1; state <= S_BLIT_RD; end
                    end else begin
                        gx <= gx + 1'b1; state <= S_BLIT_RD;
                    end
                end
                // ---------------- FILL_RECT: fill a rectangle with an index ----------------
                S_FRECT: begin
                    if (ry >= fr_h) begin
                        build_ack(OP_FRECT); state <= S_RLOAD;
                    end else if (rx >= fr_w) begin
                        rx <= 16'd0; ry <= ry + 1'b1;
                    end else begin
                        if ((fr_x + rx) < OSD_W && (fr_y + ry) < OSD_H) begin
                            fb_we    <= 1'b1;
                            fb_waddr <= (fr_y + ry) * OSD_W + (fr_x + rx);
                            fb_wdata <= fr_idx;
                        end
                        rx <= rx + 1'b1;
                    end
                end
                // ---------------- transmit response ----------------
                S_RLOAD: if (!tx_busy) begin
                    if (resp_idx < resp_total) begin
                        tx_data  <= resp[resp_idx];
                        tx_start <= 1'b1;
                        if (resp_idx >= 5'd1) resp_crc <= crc8(resp_crc, resp[resp_idx]);
                        resp_idx <= resp_idx + 1'b1;
                        state    <= S_RWAIT;
                    end else if (resp_idx == resp_total) begin
                        tx_data  <= resp_crc;
                        tx_start <= 1'b1;
                        resp_idx <= resp_idx + 1'b1;
                        state    <= S_RWAIT;
                    end else begin
                        state <= S_SYNC;
                    end
                end
                S_RWAIT: if (!tx_busy) state <= S_RLOAD;

                default: state <= S_SYNC;
            endcase
        end
    end
endmodule

`default_nettype wire
