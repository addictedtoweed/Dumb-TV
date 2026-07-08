// top_rgb.v
//
// Two-clock prototype top: parallel-RGB input + full-screen indexed OSD + UART.
//
//   pclk domain:  [bridge] -> rgb_in -> osd_compositor -> out
//   sclk domain:  rx -> uart_rx -> cmd_parser -> uart_tx -> tx
//
// Crossings: canvas (osd_fb) and palette are dual-clock BRAMs written on sclk /
// read on pclk; the config (enable + master alpha) crosses via sync2. In sim,
// video_timing + pattern_gen stands in for the bridge's parallel output.
//
// NOTE: `rst` is shared across domains for simulation simplicity; real hardware
// needs a reset synchronized into each clock domain.

`default_nettype none

module top_rgb #(
    parameter CW           = 12,
    parameter OSD_W        = 8,
    parameter OSD_H        = 4,
    parameter ACTIVE_W     = 16,
    parameter ACTIVE_H     = 8,
    parameter CLKS_PER_BIT = 8,
    parameter FB_AW        = $clog2(OSD_W*OSD_H)
)(
    input  wire        sclk,
    input  wire        pclk,
    input  wire        rst,
    input  wire        rx,
    output wire        tx,
    output wire        out_de,
    output wire        out_hsync,
    output wire        out_vsync,
    output wire [7:0]  out_r,
    output wire [7:0]  out_g,
    output wire [7:0]  out_b
);
    // ---------------- pixel-clock domain ----------------
    wire           s_hsync, s_vsync, s_de;
    wire [CW-1:0]  s_x, s_y;
    wire [7:0]     s_r, s_g, s_b;

    video_timing #(.CW(CW)) u_timing (
        .clk(pclk), .rst(rst),
        .hsync(s_hsync), .vsync(s_vsync), .de(s_de), .x(s_x), .y(s_y));
    pattern_gen #(.CW(CW)) u_pat (
        .x(s_x), .y(s_y), .de(s_de), .r(s_r), .g(s_g), .b(s_b));

    wire        p_de, p_hsync, p_vsync;
    wire [7:0]  p_r, p_g, p_b;
    rgb_in u_rgb (
        .clk(pclk),
        .in_de(s_de), .in_hsync(s_hsync), .in_vsync(s_vsync),
        .in_r(s_r), .in_g(s_g), .in_b(s_b),
        .de(p_de), .hsync(p_hsync), .vsync(p_vsync),
        .r(p_r), .g(p_g), .b(p_b));

    // ---------------- system-clock domain ----------------
    wire [7:0] rx_data;  wire rx_valid;
    wire [7:0] tx_data;  wire tx_start, tx_busy;

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(sclk), .rst(rst), .rx(rx), .data(rx_data), .valid(rx_valid));
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(sclk), .rst(rst), .data(tx_data), .start(tx_start), .tx(tx), .busy(tx_busy));

    wire [3:0]  ctrl_addr;  wire [15:0] ctrl_wdata;  wire ctrl_we;
    wire        fb_we;      wire [FB_AW-1:0] fb_waddr; wire [3:0] fb_wdata;
    wire        pal_we;     wire [3:0] pal_waddr;      wire [31:0] pal_wdata;
    wire        flip_req, flip_done;   // flip_req in sclk, flip_done in pclk (synced inside)

    cmd_parser #(.OSD_W(OSD_W), .OSD_H(OSD_H), .FB_AW(FB_AW)) u_parser (
        .clk(sclk), .rst(rst),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy),
        .ctrl_addr(ctrl_addr), .ctrl_wdata(ctrl_wdata), .ctrl_we(ctrl_we),
        .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata),
        .pal_we(pal_we), .pal_waddr(pal_waddr), .pal_wdata(pal_wdata),
        .flip_req(flip_req), .flip_done(flip_done));

    wire        osd_enable;
    wire [7:0]  osd_alpha;
    ctrl_regs u_ctrl (
        .clk(sclk), .rst(rst),
        .addr(ctrl_addr), .wdata(ctrl_wdata), .we(ctrl_we),
        .osd_enable(osd_enable), .osd_alpha(osd_alpha));

    // ---------------- CDC: config sclk -> pclk ----------------
    localparam CFG_W = 1 + 8;    // enable + master alpha
    wire [CFG_W-1:0] cfg_p;
    sync2 #(.W(CFG_W)) u_cfg_cdc (.clk(pclk), .d({osd_enable, osd_alpha}), .q(cfg_p));
    wire       p_enable = cfg_p[8];
    wire [7:0] p_alpha  = cfg_p[7:0];

    // ---------------- compositor (pixel domain; writes on sclk) ----------------
    osd_compositor #(.CW(CW), .OSD_W(OSD_W), .OSD_H(OSD_H),
                     .ACTIVE_W(ACTIVE_W), .ACTIVE_H(ACTIVE_H), .FB_AW(FB_AW)) u_osd (
        .clk(pclk), .rst(rst),
        .in_de(p_de), .in_hsync(p_hsync), .in_vsync(p_vsync),
        .in_r(p_r), .in_g(p_g), .in_b(p_b),
        .osd_enable(p_enable), .osd_alpha(p_alpha),
        .fb_wr_clk(sclk), .fb_we(fb_we), .fb_waddr(fb_waddr), .fb_wdata(fb_wdata),
        .pal_wr_clk(sclk), .pal_we(pal_we), .pal_waddr(pal_waddr), .pal_wdata(pal_wdata),
        .flip_req(flip_req), .flip_done(flip_done),
        .out_de(out_de), .out_hsync(out_hsync), .out_vsync(out_vsync),
        .out_r(out_r), .out_g(out_g), .out_b(out_b));
endmodule

`default_nettype wire
