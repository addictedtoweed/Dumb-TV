// top_uart.v
//
// Single-clock top: UART control plane driving the full-screen indexed OSD.
// The parser writes the canvas indices, the palette, and the control regs.

`default_nettype none

module top_uart #(
    parameter CW           = 12,
    parameter OSD_W        = 8,
    parameter OSD_H        = 4,
    parameter ACTIVE_W     = 16,
    parameter ACTIVE_H     = 8,
    parameter CLKS_PER_BIT = 8,
    parameter FB_AW        = $clog2(OSD_W*OSD_H)
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        rx,
    output wire        tx,
    output wire [3:0]  mux_sel,
    output wire        backlight,
    output wire        out_de,
    output wire        out_hsync,
    output wire        out_vsync,
    output wire [7:0]  out_r,
    output wire [7:0]  out_g,
    output wire [7:0]  out_b
);
    wire           hsync, vsync, de;
    wire [CW-1:0]  x, y;
    wire [7:0]     vr, vg, vb;

    video_timing #(.CW(CW)) u_timing (
        .clk(clk), .rst(rst), .hsync(hsync), .vsync(vsync), .de(de), .x(x), .y(y));
    pattern_gen #(.CW(CW)) u_pat (
        .x(x), .y(y), .de(de), .r(vr), .g(vg), .b(vb));

    wire [7:0] rx_data;  wire rx_valid;
    wire [7:0] tx_data;  wire tx_start, tx_busy;

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(clk), .rst(rst), .rx(rx), .data(rx_data), .valid(rx_valid));
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(clk), .rst(rst), .data(tx_data), .start(tx_start), .tx(tx), .busy(tx_busy));

    wire [3:0]  ctrl_addr;  wire [15:0] ctrl_wdata;  wire ctrl_we;
    wire        fb_we;      wire [FB_AW-1:0] fb_waddr; wire [3:0] fb_wdata;
    wire        pal_we;     wire [3:0] pal_waddr;      wire [31:0] pal_wdata;
    wire        flip_req, flip_done;

    cmd_parser #(.OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW)) u_parser (
        .clk(clk), .rst(rst),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy),
        .ctrl_addr(ctrl_addr), .ctrl_wdata(ctrl_wdata), .ctrl_we(ctrl_we),
        .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata),
        .pal_we(pal_we), .pal_waddr(pal_waddr), .pal_wdata(pal_wdata),
        .flip_req(flip_req), .flip_done(flip_done),
        .rx_ready(), .busy());

    wire        osd_enable;
    wire [7:0]  osd_alpha, brightness, contrast, bl_duty;

    ctrl_regs u_ctrl (
        .clk(clk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(osd_enable), .osd_alpha(osd_alpha), .mux_sel(mux_sel),
        .brightness(brightness), .contrast(contrast), .backlight(bl_duty));

    pwm u_pwm (.clk(clk), .rst(rst), .duty(bl_duty), .pwm(backlight));

    osd_compositor #(.CW(CW), .OSD_W(OSD_W), .OSD_H(OSD_H),
                     .ACTIVE_W(ACTIVE_W), .ACTIVE_H(ACTIVE_H), .FB_AW(FB_AW)) u_osd (
        .clk(clk), .rst(rst),
        .in_de(de), .in_hsync(hsync), .in_vsync(vsync),
        .in_r(vr), .in_g(vg), .in_b(vb),
        .osd_enable(osd_enable), .osd_alpha(osd_alpha),
        .brightness(brightness), .contrast(contrast),
        .fb_wr_clk(clk), .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata),
        .pal_wr_clk(clk), .pal_we(pal_we), .pal_waddr(pal_waddr), .pal_wdata(pal_wdata),
        .flip_req(flip_req), .flip_done(flip_done),
        .out_de(out_de), .out_hsync(out_hsync), .out_vsync(out_vsync),
        .out_r(out_r), .out_g(out_g), .out_b(out_b));
endmodule

`default_nettype wire
