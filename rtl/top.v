// top.v
//
// Single-clock top for the compositor unit test. The canvas (index) write port,
// the palette write port, and the control registers are exposed for cocotb to
// drive directly. video_timing + pattern_gen stand in for the RGB bridge.

`default_nettype none

module top #(
    parameter CW       = 12,
    parameter OSD_W    = 8,      // canvas width
    parameter OSD_H    = 4,      // canvas height
    parameter ACTIVE_W = 16,     // active video width
    parameter ACTIVE_H = 8,      // active video height
    parameter FB_AW    = $clog2(OSD_W*OSD_H)
)(
    input  wire        clk,
    input  wire        rst,
    // control registers
    input  wire [3:0]  ctrl_addr,
    input  wire [15:0] ctrl_wdata,
    input  wire        ctrl_we,
    // canvas (index) write port
    input  wire        fb_we,
    input  wire [FB_AW-1:0] fb_waddr,
    input  wire [3:0]  fb_wdata,
    // palette write port
    input  wire        pal_we,
    input  wire [3:0]  pal_waddr,
    input  wire [31:0] pal_wdata,
    // double-buffer flip handshake
    input  wire        flip_req,
    output wire        flip_done,
    // input mux select (INPUT_SELECT command)
    output wire [3:0]  mux_sel,
    // backlight PWM (INVERTER / LED-driver dimming)
    output wire        backlight,
    // output video stream
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

    wire           osd_enable;
    wire [7:0]     osd_alpha, brightness, contrast, bl_duty;

    video_timing #(.CW(CW)) u_timing (
        .clk(clk), .rst(rst), .hsync(hsync), .vsync(vsync), .de(de), .x(x), .y(y));
    pattern_gen #(.CW(CW)) u_pat (
        .x(x), .y(y), .de(de), .r(vr), .g(vg), .b(vb));

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
