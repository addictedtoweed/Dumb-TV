// palette.v
//
// The OSD color palette: 16 entries of packed {A, R, G, B} = 32 bits.
// Dual-clock: written by PALETTE_SET on the system/UART clock, read by the
// compositor on the pixel clock. Index 0 is transparent by convention (the
// compositor gates it), so entries 1..15 are the usable colors.
//
// Tie wr_clk = rd_clk for single-clock use.

`default_nettype none

module palette (
    // write port (system / UART clock domain)
    input  wire        wr_clk,
    input  wire        we,
    input  wire [3:0]  waddr,
    input  wire [31:0] wdata,      // {A,R,G,B}
    // read port (pixel clock domain, synchronous +1 clk)
    input  wire        rd_clk,
    input  wire [3:0]  raddr,
    output reg  [31:0] rdata
);
    reg [31:0] mem [0:15];

    always @(posedge wr_clk)
        if (we) mem[waddr] <= wdata;

    always @(posedge rd_clk)
        rdata <= mem[raddr];
endmodule

`default_nettype wire
