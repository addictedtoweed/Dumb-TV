// osd_compositor.v
//
// The heart of the product. Takes the input video stream, recovers the pixel
// coordinate from de/vsync (exactly as you would after a real DP RX), reads
// the OSD framebuffer for the matching texel, and alpha-blends it over the
// live video.
//
// LATENCY: two clocks. We pipeline around the 1-clock framebuffer read; we
// still never buffer a frame, so "DP as fast as possible / zero frame
// interpolation" stays structural. On hardware, genlock the output clock to
// the recovered input clock to keep added delay at one line, not one frame.
//
//   eff_alpha = (per-pixel fb alpha) * (master osd_alpha) / 256
//   out       = vid*(256-eff)/256 + fb_rgb*eff/256
//
// OSD_W/OSD_H are the framebuffer size (powers of two). osd_w/osd_h are the
// displayed window (<= OSD_W/OSD_H) so you can show part of it / reposition.

`default_nettype none

module osd_compositor #(
    parameter CW    = 12,
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter FB_AW = $clog2(OSD_W) + $clog2(OSD_H)
)(
    input  wire        clk,
    input  wire        rst,
    // Input video stream
    input  wire        in_de,
    input  wire        in_hsync,
    input  wire        in_vsync,
    input  wire [7:0]  in_r,
    input  wire [7:0]  in_g,
    input  wire [7:0]  in_b,
    // OSD config (from ctrl_regs)
    input  wire        osd_enable,
    input  wire [15:0] osd_x0,
    input  wire [15:0] osd_y0,
    input  wire [15:0] osd_w,
    input  wire [15:0] osd_h,
    input  wire [7:0]  osd_alpha,    // master fade, 0..255
    // OSD framebuffer write port (host / CPU)
    input  wire           fb_we,
    input  wire [FB_AW-1:0] fb_waddr,
    input  wire [31:0]    fb_wdata,
    // Output video stream (registered, +2 clk latency)
    output reg         out_de,
    output reg         out_hsync,
    output reg         out_vsync,
    output reg [7:0]   out_r,
    output reg [7:0]   out_g,
    output reg [7:0]   out_b
);
    localparam LX = $clog2(OSD_W);
    localparam LY = $clog2(OSD_H);

    // --- Coordinate recovery from de/vsync (mirrors a real DP RX front-end) ---
    reg [CW-1:0] x, y;
    reg          in_de_d;

    always @(posedge clk) begin
        if (rst) begin
            x       <= {CW{1'b0}};
            y       <= {CW{1'b0}};
            in_de_d <= 1'b0;
        end else begin
            in_de_d <= in_de;
            x <= in_de ? (x + 1'b1) : {CW{1'b0}};
            if (in_vsync)               y <= {CW{1'b0}};
            else if (in_de_d && !in_de) y <= y + 1'b1;
        end
    end

    // --- Stage 0: inside test + framebuffer read address (combinational) ---
    wire [15:0] x16 = {{(16-CW){1'b0}}, x};
    wire [15:0] y16 = {{(16-CW){1'b0}}, y};

    wire inside = osd_enable
               && (x16 >= osd_x0) && (x16 < osd_x0 + osd_w)
               && (y16 >= osd_y0) && (y16 < osd_y0 + osd_h);

    wire [CW-1:0] dx = x - osd_x0[CW-1:0];
    wire [CW-1:0] dy = y - osd_y0[CW-1:0];
    wire [FB_AW-1:0] raddr = {dy[LY-1:0], dx[LX-1:0]};

    wire [31:0] fb_rdata;
    osd_fb #(.OSD_W(OSD_W), .OSD_H(OSD_H), .AW(FB_AW)) u_fb (
        .clk(clk),
        .we(fb_we), .waddr(fb_waddr), .wdata(fb_wdata),
        .raddr(raddr), .rdata(fb_rdata)
    );

    // --- Stage 1: register video + flags to line up with the fb read data ---
    reg        de_s1, hs_s1, vs_s1, inside_s1;
    reg [7:0]  r_s1, g_s1, b_s1;

    always @(posedge clk) begin
        if (rst) begin
            de_s1 <= 1'b0; hs_s1 <= 1'b0; vs_s1 <= 1'b0; inside_s1 <= 1'b0;
            r_s1  <= 8'd0; g_s1  <= 8'd0; b_s1 <= 8'd0;
        end else begin
            de_s1     <= in_de;
            hs_s1     <= in_hsync;
            vs_s1     <= in_vsync;
            inside_s1 <= inside;
            r_s1      <= in_r;
            g_s1      <= in_g;
            b_s1      <= in_b;
        end
    end

    // --- Stage 2: blend fb texel over video, register the output ---
    wire [7:0] fb_a = fb_rdata[31:24];
    wire [7:0] fb_r = fb_rdata[23:16];
    wire [7:0] fb_g = fb_rdata[15:8];
    wire [7:0] fb_b = fb_rdata[7:0];

    wire [15:0] am    = fb_a * osd_alpha;   // per-pixel * master
    wire [7:0]  eff_a = am[15:8];           // / 256

    function [7:0] blend8;
        input [7:0] vid;
        input [7:0] ov;
        input [7:0] a;
        reg [16:0] t;
        begin
            t = vid * (9'd256 - a) + ov * a;
            blend8 = t[15:8];
        end
    endfunction

    wire [7:0] br = inside_s1 ? blend8(r_s1, fb_r, eff_a) : r_s1;
    wire [7:0] bg = inside_s1 ? blend8(g_s1, fb_g, eff_a) : g_s1;
    wire [7:0] bb = inside_s1 ? blend8(b_s1, fb_b, eff_a) : b_s1;

    always @(posedge clk) begin
        if (rst) begin
            out_de    <= 1'b0;
            out_hsync <= 1'b0;
            out_vsync <= 1'b0;
            out_r     <= 8'd0;
            out_g     <= 8'd0;
            out_b     <= 8'd0;
        end else begin
            out_de    <= de_s1;
            out_hsync <= hs_s1;
            out_vsync <= vs_s1;
            out_r     <= br;
            out_g     <= bg;
            out_b     <= bb;
        end
    end
endmodule

`default_nettype wire
