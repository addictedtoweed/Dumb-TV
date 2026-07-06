// cmd_parser.v  -- implements the Dumb-TV UART control protocol.
//
// Consumes bytes from uart_rx, decodes framed commands
//   A5 | CMD | LEN(16 LE) | PAYLOAD | CRC8        (CRC-8/SMBUS, poly 0x07)
// and drives:
//   - ctrl_regs writes (OSD enable/window/master-alpha)
//   - osd_fb framebuffer writes (graphics upload; texels stream as A,R,G,B)
// then emits an ACK / NACK / INFO response via uart_tx.
//
// Framebuffer uploads are committed on the fly (no full-frame buffer); a bad
// CRC returns NACK so the host re-sends that chunk. See docs/uart-protocol.md.

`default_nettype none

module cmd_parser #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter FB_AW = $clog2(OSD_W) + $clog2(OSD_H)
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
    // to osd_fb (framebuffer write port)
    output reg         fb_we,
    output reg [FB_AW-1:0] fb_waddr,
    output reg [31:0]  fb_wdata
);
    // ---- opcodes ----
    localparam OP_PING = 8'h01, OP_INFO  = 8'h02,
               OP_EN   = 8'h10, OP_WIN   = 8'h11, OP_ALPHA = 8'h12,
               OP_FBW  = 8'h20, OP_FBF   = 8'h21;
    localparam RSP_ACK = 8'h80, RSP_NACK = 8'h81, RSP_INFO = 8'h82;
    localparam ERR_CRC = 8'h01, ERR_LEN  = 8'h02, ERR_UNK  = 8'h03, ERR_RANGE = 8'h04;
    localparam [15:0] FB_DEPTH = OSD_W * OSD_H;   // framebuffer size in texels
    // ---- ctrl_regs addresses (match ctrl_regs.v) ----
    localparam A_EN = 4'd0, A_X0 = 4'd1, A_Y0 = 4'd2, A_W = 4'd3, A_H = 4'd4, A_ALPHA = 4'd5;
    // ---- INFO constants ----
    localparam [15:0] MAX_W = 16'd1920, MAX_H = 16'd1080;

    // ---- states ----
    localparam S_SYNC=0, S_CMD=1, S_LENL=2, S_LENH=3, S_PAY=4, S_CRC=5,
               S_EXEC=6, S_WIN=7, S_FILL=8, S_RLOAD=9, S_RWAIT=10;
    reg [3:0] state;

    reg [7:0]  cmd, crc, len_lo;
    reg [15:0] len, pay_idx;
    reg        bad_len;
    reg        range_err;         // a framebuffer write went out of bounds
    reg [7:0]  pbuf [0:7];          // payload buffer for small commands

    // fb-write streaming
    reg [15:0] fb_addr;
    reg [1:0]  tcount;
    reg [7:0]  t_a, t_r, t_g;

    // fill engine
    reg [15:0] fill_addr, fill_cnt;
    reg [31:0] fill_word;

    // window write sequencer
    reg [1:0]  wsel;

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
        resp[5]<=8'd0; resp[6]<=8'd1;        // fw major.minor
        resp[7]<=OSD_W[7:0];  resp[8]<=OSD_W[15:8];
        resp[9]<=OSD_H[7:0];  resp[10]<=OSD_H[15:8];
        resp[11]<=MAX_W[7:0]; resp[12]<=MAX_W[15:8];
        resp[13]<=MAX_H[7:0]; resp[14]<=MAX_H[15:8];
        resp[15]<=8'd0;                      // flags
        resp_total<=5'd16; resp_idx<=5'd0; resp_crc<=8'd0;
    end endtask

    wire [15:0] len_full = {rx_data, len_lo};

    always @(posedge clk) begin
        if (rst) begin
            state    <= S_SYNC;
            tx_start <= 1'b0;
            ctrl_we  <= 1'b0;
            fb_we    <= 1'b0;
        end else begin
            // one-shot defaults
            tx_start <= 1'b0;
            ctrl_we  <= 1'b0;
            fb_we    <= 1'b0;

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
                    crc     <= crc8(crc, rx_data);
                    len       <= len_full;
                    pay_idx   <= 16'd0;
                    tcount    <= 2'd0;
                    range_err <= 1'b0;
                    // length validation per command
                    case (cmd)
                        OP_PING, OP_INFO:  bad_len <= (len_full != 16'd0);
                        OP_EN, OP_ALPHA:   bad_len <= (len_full != 16'd1);
                        OP_WIN, OP_FBF:    bad_len <= (len_full != 16'd8);
                        OP_FBW:            bad_len <= (len_full < 16'd2) ||
                                                       (((len_full - 16'd2) & 16'd3) != 16'd0);
                        default:           bad_len <= 1'b0; // unknown -> NACK in EXEC
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
                            case (tcount)
                                2'd0: t_a <= rx_data;
                                2'd1: t_r <= rx_data;
                                2'd2: t_g <= rx_data;
                                2'd3: begin
                                    if (fb_addr < FB_DEPTH) begin
                                        fb_we    <= 1'b1;
                                        fb_waddr <= fb_addr[FB_AW-1:0];
                                        fb_wdata <= {t_a, t_r, t_g, rx_data}; // A,R,G,B
                                    end else begin
                                        range_err <= 1'b1;                    // out of bounds
                                    end
                                    fb_addr <= fb_addr + 1'b1;
                                end
                            endcase
                            tcount <= (tcount == 2'd3) ? 2'd0 : tcount + 1'b1;
                        end
                    end else begin
                        if (pay_idx < 16'd8) pbuf[pay_idx[2:0]] <= rx_data;
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
                        OP_WIN: begin wsel <= 2'd0; state <= S_WIN; end
                        OP_FBW: begin
                            if (range_err) build_nack(cmd, ERR_RANGE);
                            else           build_ack(cmd);
                            state <= S_RLOAD;
                        end
                        OP_FBF: begin
                            fill_addr <= {pbuf[1], pbuf[0]};
                            fill_cnt  <= {pbuf[3], pbuf[2]};
                            fill_word <= {pbuf[4], pbuf[5], pbuf[6], pbuf[7]};
                            state <= S_FILL;
                        end
                        default: begin build_nack(cmd, ERR_UNK); state <= S_RLOAD; end
                    endcase
                end
                // ---------------- OSD_WINDOW: 4 sequential ctrl writes ----------------
                S_WIN: begin
                    // address and data are driven together each cycle, so the
                    // ctrl_regs write samples a matched pair.
                    ctrl_we <= 1'b1;
                    case (wsel)
                        2'd0: begin ctrl_addr <= A_X0; ctrl_wdata <= {pbuf[1], pbuf[0]}; end
                        2'd1: begin ctrl_addr <= A_Y0; ctrl_wdata <= {pbuf[3], pbuf[2]}; end
                        2'd2: begin ctrl_addr <= A_W;  ctrl_wdata <= {pbuf[5], pbuf[4]}; end
                        2'd3: begin ctrl_addr <= A_H;  ctrl_wdata <= {pbuf[7], pbuf[6]}; end
                    endcase
                    if (wsel == 2'd3) begin build_ack(OP_WIN); state <= S_RLOAD; end
                    else              wsel <= wsel + 1'b1;
                end
                // ---------------- OSD_FB_FILL: write `count` texels ----------------
                S_FILL: begin
                    if (fill_cnt != 16'd0) begin
                        if (fill_addr < FB_DEPTH) begin
                            fb_we    <= 1'b1;
                            fb_waddr <= fill_addr[FB_AW-1:0];
                            fb_wdata <= fill_word;
                        end else begin
                            range_err <= 1'b1;                // out of bounds
                        end
                        fill_addr <= fill_addr + 1'b1;
                        fill_cnt  <= fill_cnt - 1'b1;
                    end else begin
                        if (range_err) build_nack(OP_FBF, ERR_RANGE);
                        else           build_ack(OP_FBF);
                        state <= S_RLOAD;
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
                        tx_data  <= resp_crc;        // final CRC byte
                        tx_start <= 1'b1;
                        resp_idx <= resp_idx + 1'b1;
                        state    <= S_RWAIT;
                    end else begin
                        state <= S_SYNC;             // done
                    end
                end
                S_RWAIT: if (!tx_busy) state <= S_RLOAD;

                default: state <= S_SYNC;
            endcase
        end
    end
endmodule

`default_nettype wire
