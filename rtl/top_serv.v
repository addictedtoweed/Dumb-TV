// top_serv.v
//
// Full internal-brains top: the host UART (source 0) and the on-board SERV
// RISC-V core (source 1) share one cmd_parser via cmd_mux, so BOTH can drive
// the OSD / display over the identical framed command protocol.
//
//   host UART rx --------------------------------\
//                                                 >-- cmd_mux -- cmd_parser --+
//   SERV.q -> uart_rx (internal source 1) -------/                           |
//                                                                            |
//   cmd_parser --.--> ctrl_regs (mux_sel, core_halt, picture, backlight)     |
//                '--> FW_WRITE port --> serv_soc program RAM  <--------------'
//
// Firmware is uploaded over the host link (FW_WRITE) into the core's program
// RAM while the core is held (FW_HALT); FW_START releases it. The running
// firmware bit-bangs UART frames on its GPIO `q`, which an internal uart_rx
// turns back into a command byte-stream on mux source 1 -- so the core issues
// the same commands a host would. The core cannot receive (Servant GPIO is
// output-only), so its response path (tx1) is left unconnected.
//
// The OSD video datapath is omitted here (as in top_mux) -- this top verifies
// the command/response plumbing + the SERV<->parser loop; mux_sel is exposed so
// a command's effect is observable, and FLIP is looped back.

`default_nettype none

module top_serv #(
    parameter OSD_W        = 8,
    parameter OSD_H        = 4,
    parameter CLKS_PER_BIT = 8,        // host link baud (clk cycles / bit)
    // Internal (SERV) link baud. The bit-serial core bit-bangs slowly, so its
    // link runs far below the host's -- calibrated to the firmware's per-bit
    // busy-loop (fw/dumbtv.h DUMBTV_BIT_LOOPS).
    parameter INT_CLKS_PER_BIT = 640,
    parameter MEMSIZE      = 16384,
    parameter FB_AW        = $clog2(OSD_W*OSD_H),
    parameter FW_AW        = $clog2(MEMSIZE)
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        rx,          // host link
    output wire        tx,
    output wire [3:0]  mux_sel,
    // debug taps (let a test watch the core come alive)
    output wire        core_rst,
    output wire        serv_q,
    output wire [31:0] dbg_mem_adr,
    output wire        dbg_mem_stb
);
    // ---- host UART <-> mux source 0 ----------------------------------------
    wire [7:0] s0_data;  wire s0_valid;
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx0 (
        .clk(clk), .rst(rst), .rx(rx), .data(s0_data), .valid(s0_valid));

    wire [7:0] t0_data;  wire t0_start, t0_busy;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx0 (
        .clk(clk), .rst(rst), .data(t0_data), .start(t0_start), .tx(tx), .busy(t0_busy));

    // ---- SERV core -> internal uart_rx -> mux source 1 ---------------------
    wire        q;
    assign serv_q = q;
    wire [7:0] s1_data;  wire s1_valid;
    uart_rx #(.CLKS_PER_BIT(INT_CLKS_PER_BIT)) u_rx1 (
        .clk(clk), .rst(rst), .rx(q), .data(s1_data), .valid(s1_valid));

    // SERV cannot receive (GPIO is output-only): sink its response with a tx
    // whose output is unused, but keep the busy handshake honest for the mux.
    wire [7:0] t1_data;  wire t1_start, t1_busy;  wire tx1_unused;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx1 (
        .clk(clk), .rst(rst), .data(t1_data), .start(t1_start), .tx(tx1_unused), .busy(t1_busy));

    // ---- shared parser via the arbiter -------------------------------------
    wire [7:0] p_rx_data, p_tx_data;
    wire       p_rx_valid, p_rx_ready, p_tx_start, p_tx_busy, p_busy;

    cmd_mux u_mux (
        .clk(clk), .rst(rst),
        .s0_data(s0_data), .s0_valid(s0_valid),
        .t0_data(t0_data), .t0_start(t0_start), .t0_busy(t0_busy),
        .s1_data(s1_data), .s1_valid(s1_valid),
        .t1_data(t1_data), .t1_start(t1_start), .t1_busy(t1_busy),
        .p_rx_data(p_rx_data), .p_rx_valid(p_rx_valid), .p_rx_ready(p_rx_ready),
        .p_tx_data(p_tx_data), .p_tx_start(p_tx_start), .p_tx_busy(p_tx_busy),
        .p_busy(p_busy));

    // FLIP loopback so the parser's flip handshake completes without a compositor
    wire flip_req_w;
    reg  flip_done_r;
    always @(posedge clk) flip_done_r <= rst ? 1'b0 : flip_req_w;

    wire [3:0]  ctrl_addr;  wire [15:0] ctrl_wdata;  wire ctrl_we;
    wire        fw_we;      wire [FW_AW-1:0] fw_waddr;  wire [7:0] fw_wdata;

    cmd_parser #(.OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW), .FW_AW(FW_AW)) u_parser (
        .clk(clk), .rst(rst),
        .rx_data(p_rx_data), .rx_valid(p_rx_valid),
        .tx_data(p_tx_data), .tx_start(p_tx_start), .tx_busy(p_tx_busy),
        .ctrl_addr(ctrl_addr), .ctrl_wdata(ctrl_wdata), .ctrl_we(ctrl_we),
        .fb_we(), .fb_waddr(), .fb_wdata(),
        .pal_we(), .pal_waddr(), .pal_wdata(),
        .fw_we(fw_we), .fw_waddr(fw_waddr), .fw_wdata(fw_wdata),
        .flip_req(flip_req_w), .flip_done(flip_done_r),
        .rx_ready(p_rx_ready), .busy(p_busy));

    // control registers: mux_sel observable; core_halt gates the SERV core
    wire core_halt_w;
    assign core_rst = core_halt_w;
    ctrl_regs u_ctrl (
        .clk(clk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(), .osd_alpha(), .mux_sel(mux_sel),
        .brightness(), .contrast(), .backlight(), .core_halt(core_halt_w));

    // ---- the SERV SoC: firmware loaded via the parser's FW_WRITE port -------
    serv_soc #(.MEMSIZE(MEMSIZE)) u_serv (
        .clk(clk), .rst(rst), .core_halt(core_halt_w),
        .i_host_we(fw_we), .i_host_adr(fw_waddr), .i_host_dat(fw_wdata),
        .q(q),
        .dbg_mem_adr(dbg_mem_adr), .dbg_mem_stb(dbg_mem_stb));
endmodule

`default_nettype wire
