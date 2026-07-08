// osd_fb_bram.v  -- OSD canvas in on-chip block RAM (default backend).
//
// Selected by the build (CANVAS=bram). Double-buffered: holds TWO canvases
// (bank 0 / bank 1). The compositor reads the front bank (rd_bank) and all host
// writes go to the back bank (wr_bank); FLIP swaps which is which at VSync.
//
//   write port : wr_clk, we, wr_bank, waddr (linear), wdata (4-bit index)  [host clk]
//   read  port : rd_clk, rd_bank, rd_cx, rd_cy, rd_newframe -> rdata (4-bit) [pixel clk]
//
// rd_newframe pulses at frame start; the BRAM backend ignores it (it is there
// for the PSRAM backend's line-buffer prefetch). Read is a plain 1-clock access.

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
    input  wire            wr_bank,
    input  wire [AW-1:0]   waddr,
    input  wire [3:0]      wdata,
    // read port (pixel clock domain, synchronous +1 clk)
    input  wire            rd_clk,
    input  wire            rd_bank,
    input  wire [CXW-1:0]  rd_cx,
    input  wire [CYW-1:0]  rd_cy,
    input  wire            rd_newframe,
    output reg  [3:0]      rdata
);
    localparam DEPTH = OSD_W * OSD_H;
    reg [3:0] mem [0:(2*DEPTH)-1];

    wire [AW:0] waddr_full = (wr_bank ? DEPTH[AW:0] : {(AW+1){1'b0}}) + {1'b0, waddr};
    wire [AW:0] rlin       = rd_cy * OSD_W + rd_cx;
    wire [AW:0] raddr_full  = (rd_bank ? DEPTH[AW:0] : {(AW+1){1'b0}}) + rlin;

    always @(posedge wr_clk)
        if (we) mem[waddr_full] <= wdata;

    always @(posedge rd_clk)
        rdata <= mem[raddr_full];

    wire _unused = &{1'b0, rd_newframe};   // consumed by the PSRAM backend
endmodule

`default_nettype wire
