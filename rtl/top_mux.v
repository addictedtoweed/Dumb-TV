// top_mux.v
//
// Test/reference top for the two-source command path: two independent UART
// links (host = source 0, "internal" = source 1) share one cmd_parser via
// cmd_mux. Each link gets its own responses. This is the seam the SERV core
// plugs into later (its UART becomes source 1); here both are real UARTs so the
// arbitration + response routing can be exercised in simulation.
//
// The OSD datapath is omitted -- this top verifies the command/response plumbing
// (mux_sel is exposed so a command's effect is observable, and flip_done is
// looped back so FLIP still completes).

`default_nettype none

module top_mux #(
    parameter OSD_W        = 8,
    parameter OSD_H        = 4,
    parameter CLKS_PER_BIT = 8,
    parameter FB_AW        = $clog2(OSD_W*OSD_H)
)(
    input  wire       clk,
    input  wire       rst,
    input  wire       rx0,        // host link
    output wire       tx0,
    input  wire       rx1,        // internal / SERV link
    output wire       tx1,
    output wire [3:0] mux_sel,
    // SERV firmware RAM: core reset + a read-back port (stands in for the core)
    output wire       core_rst,
    input  wire [13:0] fw_raddr,
    output wire [7:0]  fw_rdata
);
    // UART receivers -> byte streams
    wire [7:0] s0_data, s1_data;  wire s0_valid, s1_valid;
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx0 (
        .clk(clk), .rst(rst), .rx(rx0), .data(s0_data), .valid(s0_valid));
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx1 (
        .clk(clk), .rst(rst), .rx(rx1), .data(s1_data), .valid(s1_valid));

    // UART transmitters <- routed responses
    wire [7:0] t0_data, t1_data;  wire t0_start, t1_start, t0_busy, t1_busy;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx0 (
        .clk(clk), .rst(rst), .data(t0_data), .start(t0_start), .tx(tx0), .busy(t0_busy));
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx1 (
        .clk(clk), .rst(rst), .data(t1_data), .start(t1_start), .tx(tx1), .busy(t1_busy));

    // parser hookup
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
    wire        fw_we;      wire [13:0] fw_waddr;    wire [7:0] fw_wdata;

    cmd_parser #(.OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW)) u_parser (
        .clk(clk), .rst(rst),
        .rx_data(p_rx_data), .rx_valid(p_rx_valid),
        .tx_data(p_tx_data), .tx_start(p_tx_start), .tx_busy(p_tx_busy),
        .ctrl_addr(ctrl_addr), .ctrl_wdata(ctrl_wdata), .ctrl_we(ctrl_we),
        .fb_we(), .fb_waddr(), .fb_wdata(),
        .pal_we(), .pal_waddr(), .pal_wdata(),
        .fw_we(fw_we), .fw_waddr(fw_waddr), .fw_wdata(fw_wdata),
        .flip_req(flip_req_w), .flip_done(flip_done_r),
        .rx_ready(p_rx_ready), .busy(p_busy));

    // control registers (so a command's effect -- e.g. mux_sel -- is observable)
    ctrl_regs u_ctrl (
        .clk(clk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(), .osd_alpha(), .mux_sel(mux_sel),
        .brightness(), .contrast(), .backlight(), .core_halt(core_rst));

    // firmware / program RAM: host writes on port A, read-back on port B
    fw_mem u_fw (
        .wr_clk(clk), .we(fw_we), .waddr(fw_waddr), .wdata(fw_wdata),
        .rd_clk(clk), .raddr(fw_raddr), .rdata(fw_rdata));
endmodule

`default_nettype wire
