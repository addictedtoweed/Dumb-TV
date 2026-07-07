// osd_fb.v
//
// The OSD canvas: a small dual-clock block-RAM holding the overlay as 4-bit
// palette indices (index 0 = transparent). Written on the host/UART clock,
// read on the pixel clock. OSD_W x OSD_H is the *canvas* resolution; the
// compositor upscales it to the full active area, so the canvas stays small.
//
// Tie wr_clk = rd_clk for single-clock use. OSD_W/OSD_H need not be powers of
// two (the compositor computes the linear address).

`default_nettype none

module osd_fb #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter AW    = $clog2(OSD_W*OSD_H)
)(
    // write port (system / UART clock domain)
    input  wire           wr_clk,
    input  wire           we,
    input  wire [AW-1:0]  waddr,
    input  wire [3:0]     wdata,      // 4-bit palette index
    // read port (pixel clock domain, synchronous +1 clk)
    input  wire           rd_clk,
    input  wire [AW-1:0]  raddr,
    output reg  [3:0]     rdata
);
    reg [3:0] mem [0:(OSD_W*OSD_H)-1];

    always @(posedge wr_clk)
        if (we) mem[waddr] <= wdata;

    always @(posedge rd_clk)
        rdata <= mem[raddr];
endmodule

`default_nettype wire
