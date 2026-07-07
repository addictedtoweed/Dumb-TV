// osd_fb_psram.v  -- OSD canvas backed by EXTERNAL memory (SDRAM/PSRAM/HyperRAM).
//
// Selected by the build (CANVAS=psram in the Makefile). Drop-in for
// osd_fb_bram.v: identical ports, so osd_compositor is unchanged. This lets a
// large / high-res / double-buffered canvas live in the cheap PSRAM that many
// low-cost FPGAs bundle (e.g. 64 Mbit), instead of on-chip BRAM.
//
//   write port : wr_clk, we, waddr (linear), wdata (4-bit index)   [host clock]
//   read  port : rd_clk, rd_cx, rd_cy, rd_newframe -> rdata (4-bit) [pixel clock]
//
// Why the read port is (cx, cy, new_frame) rather than a linear address: an
// external memory cannot do a random 1-clock read every pixel. The real backend
// hides that latency with a BRAM LINE-BUFFER PREFETCH: while the current canvas
// row is being displayed, the *next* row is burst-read from external memory into
// a second line buffer, and the buffers swap when rd_cy advances. rd_cy tells it
// which row, rd_newframe restarts the prefetch at row 0 during vertical blank.
// Because the OSD is upscaled, each canvas row feeds several screen lines, so
// there is ample time to prefetch the next one.
//
// ============================ INTEGRATION NOTE ============================
// In SIMULATION the external memory is the behavioral `cmem` below, read with a
// 1-clock access -- functionally exact, so the whole OSD verifies against this
// backend. On HARDWARE, replace the marked block with your board's memory
// controller (HyperRAM/PSRAM/SDRAM) behind the line-buffer prefetch described
// above; the module boundary and the rd_cx/rd_cy/rd_newframe contract stay the
// same. See docs (canvas storage seam).
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
    input  wire [AW-1:0]   waddr,
    input  wire [3:0]      wdata,
    input  wire            rd_clk,
    input  wire [CXW-1:0]  rd_cx,
    input  wire [CYW-1:0]  rd_cy,
    input  wire            rd_newframe,
    output reg  [3:0]      rdata
);
    // ===================== EXTERNAL MEMORY (replace on HW) =====================
    // Behavioral stand-in for the external PSRAM/HyperRAM/SDRAM array. On a real
    // board this is a memory controller; here it is a plain array so the OSD
    // pipeline verifies end-to-end against the PSRAM-selected build.
    reg [3:0] cmem [0:(OSD_W*OSD_H)-1];

    always @(posedge wr_clk)
        if (we) cmem[waddr] <= wdata;         // host writes -> external memory

    // Read path. Simulation: a correct 1-clock read of the backing store.
    // Hardware: a BRAM line-buffer prefetched from `cmem` over the memory
    // controller, indexed by rd_cx, refilled for rd_cy / restarted on
    // rd_newframe (see header). The (cx, cy, new_frame) contract is what makes
    // that prefetch possible without changing the compositor.
    always @(posedge rd_clk)
        rdata <= cmem[rd_cy * OSD_W + rd_cx];
    // =========================================================================

    wire _unused = &{1'b0, rd_newframe};      // consumed by the HW prefetch
endmodule

`default_nettype wire
