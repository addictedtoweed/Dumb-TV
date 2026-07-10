// top_lvds.v
//
// The OUTPUT=lvds seam: the full UART-driven OSD pipeline (like top_uart) with a
// native-LVDS output stage. The compositor's parallel RGB feeds rgb_to_lvds,
// whose mapping is set at runtime by the LVDS command (ctrl_regs.lvds_cfg). The
// 7-bit-per-lane words (d0..d3 + clk_lane) go to per-lane 7:1 OSERDES + LVDS I/O
// primitives at synthesis (device-specific, not in this module).
//
// lvds_cfg bit layout (matches the LVDS command payload, little-endian):
//   [0] bpp24  [1] jeida  [2] clk_pol  [3] de_pol  [4] hs_pol  [5] vs_pol
//   [9:6] data_pol[3:0]

`default_nettype none

module top_lvds #(
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
    // composited parallel RGB (the rgb_to_lvds input, exposed for observability)
    output wire        out_de, out_hsync, out_vsync,
    output wire [7:0]  out_r, out_g, out_b,
    // native-LVDS lane words (to the OSERDES/IO at synthesis)
    output wire [6:0]  lvds_d0, lvds_d1, lvds_d2, lvds_d3, lvds_clk,
    output wire        lvds_word_en
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
        .fw_we(), .fw_waddr(), .fw_wdata(),
        .flip_req(flip_req), .flip_done(flip_done),
        .rx_ready(), .busy());

    wire        osd_enable;
    wire [7:0]  osd_alpha, brightness, contrast, bl_duty;
    wire [15:0] lvds_cfg;

    ctrl_regs u_ctrl (
        .clk(clk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(osd_enable), .osd_alpha(osd_alpha), .mux_sel(mux_sel),
        .brightness(brightness), .contrast(contrast), .backlight(bl_duty),
        .core_halt(), .lvds_cfg(lvds_cfg));

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

    // native-LVDS output stage: compositor RGB -> FPD-Link lane words
    rgb_to_lvds u_lvds (
        .clk(clk), .rst(rst),
        .de(out_de), .hs(out_hsync), .vs(out_vsync),
        .r(out_r), .g(out_g), .b(out_b),
        .cfg_bpp24(lvds_cfg[0]), .cfg_jeida(lvds_cfg[1]),
        .cfg_data_pol(lvds_cfg[9:6]), .cfg_clk_pol(lvds_cfg[2]),
        .cfg_de_pol(lvds_cfg[3]), .cfg_hs_pol(lvds_cfg[4]), .cfg_vs_pol(lvds_cfg[5]),
        .d0(lvds_d0), .d1(lvds_d1), .d2(lvds_d2), .d3(lvds_d3),
        .clk_lane(lvds_clk), .word_en(lvds_word_en));
endmodule

`default_nettype wire
