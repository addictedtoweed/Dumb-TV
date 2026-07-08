// osd_compositor.v
//
// Full-screen indexed OSD compositor.
//
//   active (x,y) --upscale--> canvas (cx,cy) --> canvas index --> palette
//        |                                                            |
//        video (delayed to match) --------- alpha-blend <------------ RGBA
//
// The low-res canvas (OSD_W x OSD_H, 4-bit indices) is stretched to the full
// active area (ACTIVE_W x ACTIVE_H) by a nearest-neighbour DDA upscaler, so an
// integer scale (e.g. 640x360 -> 1920x1080, 3x) is crisp. Each canvas texel is
// a palette index; index 0 is transparent (video shows through). The fetched
// palette RGBA is alpha-blended (per-pixel alpha * master fade) into the video.
//
// Latency: 3 clocks (upscale addr -> canvas read -> palette read -> blend). No
// frame buffering. Both RAMs are dual-clock so the write side (blit / UART) can
// run on a separate system clock; the compositor reads on the pixel clock.

`default_nettype none

module osd_compositor #(
    parameter CW       = 12,
    parameter OSD_W    = 8,      // canvas width  (texels)
    parameter OSD_H    = 4,      // canvas height
    parameter ACTIVE_W = 16,     // active video width  (pixels)
    parameter ACTIVE_H = 8,      // active video height
    parameter FB_AW    = $clog2(OSD_W*OSD_H)
)(
    input  wire        clk,      // pixel clock
    input  wire        rst,
    // input video stream
    input  wire        in_de,
    input  wire        in_hsync,
    input  wire        in_vsync,
    input  wire [7:0]  in_r,
    input  wire [7:0]  in_g,
    input  wire [7:0]  in_b,
    // config (pixel-domain)
    input  wire        osd_enable,
    input  wire [7:0]  osd_alpha,       // master fade
    // canvas (index) write port
    input  wire        fb_wr_clk,
    input  wire        fb_we,
    input  wire [FB_AW-1:0] fb_waddr,
    input  wire [3:0]  fb_wdata,        // 4-bit index
    // palette write port
    input  wire        pal_wr_clk,
    input  wire        pal_we,
    input  wire [3:0]  pal_waddr,
    input  wire [31:0] pal_wdata,       // {A,R,G,B}
    // double-buffer flip handshake: flip_req (toggle, fb_wr_clk domain) requests
    // a front/back swap; it is applied at the next VSync and acknowledged by
    // toggling flip_done (pixel-clock domain).
    input  wire        flip_req,
    output reg         flip_done,
    // output video stream (registered, +3 clk)
    output reg         out_de,
    output reg         out_hsync,
    output reg         out_vsync,
    output reg [7:0]   out_r,
    output reg [7:0]   out_g,
    output reg [7:0]   out_b
);
    localparam FRAC = 16;
    localparam CXW  = $clog2(OSD_W);
    localparam CYW  = $clog2(OSD_H);
    localparam [31:0] X_STEP = (OSD_W << FRAC) / ACTIVE_W;   // canvas texels / pixel
    localparam [31:0] Y_STEP = (OSD_H << FRAC) / ACTIVE_H;

    // ---- nearest-neighbour upscaler: accumulate the canvas coordinate ----
    reg [31:0] x_acc, y_acc;
    reg        in_de_d;
    always @(posedge clk) begin
        if (rst) begin x_acc <= 32'd0; y_acc <= 32'd0; in_de_d <= 1'b0; end
        else begin
            in_de_d <= in_de;
            x_acc <= in_de ? (x_acc + X_STEP) : 32'd0;      // reset each line
            if (in_vsync)               y_acc <= 32'd0;      // reset each frame
            else if (in_de_d && !in_de) y_acc <= y_acc + Y_STEP;   // next line
        end
    end
    wire [CXW-1:0] cx = x_acc[FRAC + CXW - 1 : FRAC];
    wire [CYW-1:0] cy = y_acc[FRAC + CYW - 1 : FRAC];

    // ---- double-buffer: read the front bank, write the back bank ----
    // flip_req (fb_wr_clk domain) crosses into the pixel clock; a pending flip is
    // applied at VSync (no tearing) and acknowledged via flip_done. The write
    // side needs the *back* bank, so front_bank is synced into fb_wr_clk.
    reg  front_bank;
    reg  flip_req_s1, flip_req_s2, flip_req_seen, flip_pending;
    always @(posedge clk) begin
        if (rst) begin
            front_bank   <= 1'b0;
            flip_req_s1  <= 1'b0; flip_req_s2 <= 1'b0;
            flip_req_seen<= 1'b0; flip_pending<= 1'b0;
            flip_done    <= 1'b0;
        end else begin
            {flip_req_s2, flip_req_s1} <= {flip_req_s1, flip_req};   // 2FF sync
            if (flip_req_s2 != flip_req_seen) begin
                flip_req_seen <= flip_req_s2;
                flip_pending  <= 1'b1;                                // new flip asked
            end
            if (in_vsync && flip_pending) begin
                front_bank   <= ~front_bank;                         // swap at VSync
                flip_pending <= 1'b0;
                flip_done    <= ~flip_done;                          // ack the swap
            end
        end
    end

    // back bank in the write clock domain (= ~front)
    reg front_wr1, front_wr2;
    always @(posedge fb_wr_clk) begin
        if (rst) begin front_wr1 <= 1'b0; front_wr2 <= 1'b0; end
        else          {front_wr2, front_wr1} <= {front_wr1, front_bank};
    end
    wire wr_bank = ~front_wr2;

    // ---- canvas (indexed) : read gives index one clock later ----
    // The (bank, cx, cy, new_frame) read port is the swappable canvas-storage
    // seam: osd_fb is osd_fb_bram.v (BRAM) or osd_fb_psram.v (external memory),
    // selected by the build (CANVAS=bram|psram).
    wire [3:0] cidx;
    osd_fb #(.OSD_W(OSD_W), .OSD_H(OSD_H), .AW(FB_AW)) u_fb (
        .wr_clk(fb_wr_clk), .we(fb_we), .wr_bank(wr_bank), .waddr(fb_waddr), .wdata(fb_wdata),
        .rd_clk(clk), .rd_bank(front_bank), .rd_cx(cx), .rd_cy(cy),
        .rd_newframe(in_vsync), .rdata(cidx));

    // ---- palette : addressed by the canvas index, RGBA one clock later ----
    wire [31:0] pcolor;
    palette u_pal (
        .wr_clk(pal_wr_clk), .we(pal_we), .waddr(pal_waddr), .wdata(pal_wdata),
        .rd_clk(clk), .raddr(cidx), .rdata(pcolor));

    // ---- delay video + sync by the two RAM reads, carry the index ----
    reg de1, hs1, vs1, de2, hs2, vs2;
    reg [7:0] r1, g1, b1, r2, g2, b2;
    reg [3:0] idx2;
    always @(posedge clk) begin
        if (rst) begin
            de1<=0; hs1<=0; vs1<=0; de2<=0; hs2<=0; vs2<=0;
            r1<=0; g1<=0; b1<=0; r2<=0; g2<=0; b2<=0; idx2<=0;
        end else begin
            de1<=in_de; hs1<=in_hsync; vs1<=in_vsync; r1<=in_r; g1<=in_g; b1<=in_b;
            de2<=de1;   hs2<=hs1;      vs2<=vs1;      r2<=r1;   g2<=g1;   b2<=b1;
            idx2<=cidx;                              // index for the pixel in r2/g2/b2
        end
    end

    // ---- blend palette color over video (stage aligned with pcolor) ----
    wire [7:0] pa = pcolor[31:24];
    wire [7:0] pr = pcolor[23:16];
    wire [7:0] pg = pcolor[15:8];
    wire [7:0] pb = pcolor[7:0];

    // index 0 is transparent; else weight = per-pixel alpha * master (0..256)
    wire [8:0]  pa_w     = pa        + (pa        >> 7);
    wire [8:0]  master_w = osd_alpha + (osd_alpha >> 7);
    wire [16:0] effp     = pa_w * master_w;
    wire [8:0]  eff_full = effp[16:8];
    wire        show     = osd_enable && (idx2 != 4'd0);
    wire [8:0]  eff_w    = show ? eff_full : 9'd0;

    function [7:0] blend8;
        input [7:0] vid;
        input [7:0] ov;
        input [8:0] w;                 // 0..256
        reg [16:0] t;
        begin
            t = vid * (9'd256 - w) + ov * w;
            blend8 = t[15:8];
        end
    endfunction

    wire [7:0] br = blend8(r2, pr, eff_w);
    wire [7:0] bg = blend8(g2, pg, eff_w);
    wire [7:0] bb = blend8(b2, pb, eff_w);

    always @(posedge clk) begin
        if (rst) begin
            out_de<=0; out_hsync<=0; out_vsync<=0; out_r<=0; out_g<=0; out_b<=0;
        end else begin
            out_de<=de2; out_hsync<=hs2; out_vsync<=vs2;
            out_r<=br;   out_g<=bg;      out_b<=bb;
        end
    end
endmodule

`default_nettype wire
