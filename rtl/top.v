// top.v
//
// Wires the scaffold together:
//
//   video_timing + pattern_gen   (stand-in for DisplayPort RX)
//        |  in_de/sync/rgb
//        v
//   osd_compositor  <--- ctrl_regs   (stand-in for UART control plane)
//        |  ^   \------ osd_fb write port (stand-in for host image upload)
//        |  out_de/sync/rgb
//        v
//   (in the product: LVDS at 1080p, or DP TX -> swappable panel adapter)
//
// For 1080p synthesis, override the timing parameters on video_timing.

`default_nettype none

module top #(
    parameter CW    = 12,
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter FB_AW = $clog2(OSD_W) + $clog2(OSD_H)
)(
    input  wire        clk,
    input  wire        rst,
    // Control-plane write port (driven by UART parser, or cocotb)
    input  wire [3:0]  ctrl_addr,
    input  wire [15:0] ctrl_wdata,
    input  wire        ctrl_we,
    // OSD framebuffer write port (host image upload, or cocotb)
    input  wire           fb_we,
    input  wire [FB_AW-1:0] fb_waddr,
    input  wire [31:0]    fb_wdata,
    // Output video stream
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
    wire [15:0]    osd_x0, osd_y0, osd_w, osd_h;
    wire [7:0]     osd_alpha;

    video_timing #(.CW(CW)) u_timing (
        .clk(clk), .rst(rst),
        .hsync(hsync), .vsync(vsync), .de(de), .x(x), .y(y)
    );

    pattern_gen #(.CW(CW)) u_pat (
        .x(x), .y(y), .de(de), .r(vr), .g(vg), .b(vb)
    );

    ctrl_regs u_ctrl (
        .clk(clk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(osd_enable),
        .osd_x0(osd_x0), .osd_y0(osd_y0), .osd_w(osd_w), .osd_h(osd_h),
        .osd_alpha(osd_alpha)
    );

    osd_compositor #(.CW(CW), .OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW)) u_osd (
        .clk(clk), .rst(rst),
        .in_de(de), .in_hsync(hsync), .in_vsync(vsync),
        .in_r(vr), .in_g(vg), .in_b(vb),
        .osd_enable(osd_enable),
        .osd_x0(osd_x0), .osd_y0(osd_y0), .osd_w(osd_w), .osd_h(osd_h),
        .osd_alpha(osd_alpha),
        .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata),
        .out_de(out_de), .out_hsync(out_hsync), .out_vsync(out_vsync),
        .out_r(out_r), .out_g(out_g), .out_b(out_b)
    );
endmodule

`default_nettype wire
