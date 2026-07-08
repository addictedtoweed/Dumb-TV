// osd_fb_psram.v  -- OSD canvas backed by EXTERNAL memory (SDRAM/PSRAM/HyperRAM).
//
// Selected by the build (CANVAS=psram). Drop-in for osd_fb_bram.v: identical
// ports (double-buffered: bank 0 / bank 1, rd_bank front, wr_bank back), so the
// compositor is unchanged. Lets a large / high-res / double-buffered canvas live
// in the cheap external PSRAM many low-cost FPGAs bundle (~64 Mbit).
//
//   write port : wr_clk, we, wr_bank, waddr (linear), wdata (4-bit index)  [host clk]
//   read  port : rd_clk, rd_bank, rd_cx, rd_cy, rd_newframe -> rdata (4-bit) [pixel clk]
//
// The read port is (bank, cx, cy, new_frame) rather than a linear address so the
// real backend can hide external-memory latency with a BRAM LINE-BUFFER PREFETCH:
// while the current canvas row displays, the next row is burst-read into a second
// line buffer and the buffers swap when rd_cy advances; rd_newframe restarts the
// prefetch at row 0 during vblank. Because the OSD is upscaled, each canvas row
// feeds several screen lines, leaving ample time to prefetch.
//
// ============================ INTEGRATION NOTE ============================
// In SIMULATION the external memory is the behavioral `cmem` below, read with a
// 1-clock access -- functionally exact, so the whole OSD verifies against this
// backend. On HARDWARE, replace the marked block with your board's memory
// controller behind the line-buffer prefetch described above; the module
// boundary and the (bank, cx, cy, new_frame) contract stay the same.
// =========================================================================

`default_nettype none

module osd_fb #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter AW    = $clog2(OSD_W*OSD_H),
    parameter CXW   = $clog2(OSD_W),
    parameter CYW   = $clog2(OSD_H)
)(
    input  wire            wr_clk,
    input  wire            we,
    input  wire            wr_bank,
    input  wire [AW-1:0]   waddr,
    input  wire [3:0]      wdata,
    input  wire            rd_clk,
    input  wire            rd_bank,
    input  wire [CXW-1:0]  rd_cx,
    input  wire [CYW-1:0]  rd_cy,
    input  wire            rd_newframe,
    output reg  [3:0]      rdata
);
    localparam DEPTH = OSD_W * OSD_H;

    // ===================== EXTERNAL MEMORY (replace on HW) =====================
    // Behavioral stand-in for the external PSRAM/HyperRAM/SDRAM array (both
    // canvas banks). On a real board this is a memory controller; here a plain
    // array so the OSD pipeline verifies end-to-end against the PSRAM build.
    reg [3:0] cmem [0:(2*DEPTH)-1];

    wire [AW:0] waddr_full = (wr_bank ? DEPTH[AW:0] : {(AW+1){1'b0}}) + {1'b0, waddr};
    wire [AW:0] rlin       = rd_cy * OSD_W + rd_cx;
    wire [AW:0] raddr_full  = (rd_bank ? DEPTH[AW:0] : {(AW+1){1'b0}}) + rlin;

    always @(posedge wr_clk)
        if (we) cmem[waddr_full] <= wdata;    // host writes -> external memory

    // Read path. Simulation: a correct 1-clock read. Hardware: a BRAM
    // line-buffer prefetched from cmem over the memory controller, indexed by
    // rd_cx, refilled for rd_cy / restarted on rd_newframe (see header).
    always @(posedge rd_clk)
        rdata <= cmem[raddr_full];
    // =========================================================================

    wire _unused = &{1'b0, rd_newframe};      // consumed by the HW prefetch
endmodule

`default_nettype wire
