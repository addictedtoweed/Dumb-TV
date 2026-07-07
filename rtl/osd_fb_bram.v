// osd_fb_bram.v  -- OSD canvas stored in on-chip block RAM (default backend).
//
// Selected by the build (CANVAS=bram in the Makefile). Presents the canvas
// storage contract used by osd_compositor:
//   write port : wr_clk, we, waddr (linear), wdata (4-bit index)   [host clock]
//   read  port : rd_clk, rd_cx, rd_cy, rd_newframe -> rdata (4-bit) [pixel clock]
// rd_newframe pulses at the start of each frame; the BRAM backend ignores it
// (it is there for the PSRAM backend's line-buffer prefetch). The read is a
// plain 1-clock dual-port RAM access.
//
// A 640x360 4bpp canvas is ~112 KB single-buffered -- fine for BRAM. For a
// larger / higher-res / double-buffered canvas, build CANVAS=psram instead.

`default_nettype none

module osd_fb #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter AW    = $clog2(OSD_W*OSD_H),
    parameter CXW   = $clog2(OSD_W),
    parameter CYW   = $clog2(OSD_H)
)(
    // write port (system / UART clock domain)
    input  wire            wr_clk,
    input  wire            we,
    input  wire [AW-1:0]   waddr,
    input  wire [3:0]      wdata,
    // read port (pixel clock domain, synchronous +1 clk)
    input  wire            rd_clk,
    input  wire [CXW-1:0]  rd_cx,
    input  wire [CYW-1:0]  rd_cy,
    input  wire            rd_newframe,   // unused here (see PSRAM backend)
    output reg  [3:0]      rdata
);
    reg [3:0] mem [0:(OSD_W*OSD_H)-1];

    always @(posedge wr_clk)
        if (we) mem[waddr] <= wdata;

    always @(posedge rd_clk)
        rdata <= mem[rd_cy * OSD_W + rd_cx];

    // rd_newframe is part of the canvas contract but only the PSRAM backend
    // needs it; reference it so lint stays quiet.
    wire _unused = &{1'b0, rd_newframe};
endmodule

`default_nettype wire
