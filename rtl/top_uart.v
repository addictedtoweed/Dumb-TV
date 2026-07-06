// top_uart.v
//
// Full prototype top: the UART control plane driving the OSD video pipeline.
//
//   rx --> uart_rx --> cmd_parser --+--> ctrl_regs ---\
//                          |        |                  osd_compositor --> out
//                          |        +--> osd_fb write -/        ^
//                          +--> uart_tx --> tx                  |
//   video_timing + pattern_gen (DP RX stand-in) -----------------
//
// Same video pipeline as top.v, but the control/framebuffer ports are driven by
// the serial command parser instead of being exposed for direct test poking.

`default_nettype none

module top_uart #(
    parameter CW           = 12,
    parameter OSD_W        = 8,
    parameter OSD_H        = 4,
    parameter CLKS_PER_BIT = 8,
    parameter FB_AW        = $clog2(OSD_W) + $clog2(OSD_H)
)(
    input  wire        clk,
    input  wire        rst,
    // serial control link to the host (Pi)
    input  wire        rx,
    output wire        tx,
    // output video stream
    output wire        out_de,
    output wire        out_hsync,
    output wire        out_vsync,
    output wire [7:0]  out_r,
    output wire [7:0]  out_g,
    output wire [7:0]  out_b
);
    // --- video source (stand-in for DP RX) ---
    wire           hsync, vsync, de;
    wire [CW-1:0]  x, y;
    wire [7:0]     vr, vg, vb;

    video_timing #(.CW(CW)) u_timing (
        .clk(clk), .rst(rst), .hsync(hsync), .vsync(vsync), .de(de), .x(x), .y(y));
    pattern_gen #(.CW(CW)) u_pat (
        .x(x), .y(y), .de(de), .r(vr), .g(vg), .b(vb));

    // --- UART RX/TX ---
    wire [7:0] rx_data;  wire rx_valid;
    wire [7:0] tx_data;  wire tx_start, tx_busy;

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(clk), .rst(rst), .rx(rx), .data(rx_data), .valid(rx_valid));
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(clk), .rst(rst), .data(tx_data), .start(tx_start), .tx(tx), .busy(tx_busy));

    // --- command parser ---
    wire [3:0]  ctrl_addr;  wire [15:0] ctrl_wdata;  wire ctrl_we;
    wire        fb_we;      wire [FB_AW-1:0] fb_waddr; wire [31:0] fb_wdata;

    cmd_parser #(.OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW)) u_parser (
        .clk(clk), .rst(rst),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy),
        .ctrl_addr(ctrl_addr), .ctrl_wdata(ctrl_wdata), .ctrl_we(ctrl_we),
        .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata));

    // --- OSD config registers ---
    wire        osd_enable;
    wire [15:0] osd_x0, osd_y0, osd_w, osd_h;
    wire [7:0]  osd_alpha;

    ctrl_regs u_ctrl (
        .clk(clk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(osd_enable),
        .osd_x0(osd_x0), .osd_y0(osd_y0), .osd_w(osd_w), .osd_h(osd_h),
        .osd_alpha(osd_alpha));

    // --- compositor (instantiates the OSD framebuffer internally) ---
    osd_compositor #(.CW(CW), .OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW)) u_osd (
        .clk(clk), .rst(rst),
        .in_de(de), .in_hsync(hsync), .in_vsync(vsync),
        .in_r(vr), .in_g(vg), .in_b(vb),
        .osd_enable(osd_enable),
        .osd_x0(osd_x0), .osd_y0(osd_y0), .osd_w(osd_w), .osd_h(osd_h),
        .osd_alpha(osd_alpha),
        .fb_wr_clk(clk),
        .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata),
        .out_de(out_de), .out_hsync(out_hsync), .out_vsync(out_vsync),
        .out_r(out_r), .out_g(out_g), .out_b(out_b));
endmodule

`default_nettype wire
