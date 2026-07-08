// fw_mem.v  -- SERV firmware / program RAM (dual-port).
//
// Byte-addressable RAM holding the RISC-V firmware blob. Port A is written by the
// host (FW_WRITE, streamed over the serial link). Port B is the core's access
// port (instruction fetch / load-store for the SERV core, wired in a later
// step; used for read-back verification for now). Hold the core in reset while
// writing (FW_HALT), release to run (FW_START).
//
// 16 KB is plenty for an RV32I control + IR-learning loop (14-bit address).

`default_nettype none

module fw_mem #(
    parameter DEPTH = 16384,
    parameter AW    = $clog2(DEPTH)
)(
    // port A: host write (system clock)
    input  wire          wr_clk,
    input  wire          we,
    input  wire [AW-1:0] waddr,
    input  wire [7:0]    wdata,
    // port B: core / read-back
    input  wire          rd_clk,
    input  wire [AW-1:0] raddr,
    output reg  [7:0]    rdata
);
    reg [7:0] mem [0:DEPTH-1];

    always @(posedge wr_clk)
        if (we) mem[waddr] <= wdata;

    always @(posedge rd_clk)
        rdata <= mem[raddr];
endmodule

`default_nettype wire
