// serv_ram_hw.v  -- host-writable program RAM for the SERV core.
//
// A Wishbone RAM matching the vendored `servant_ram` interface (32-bit word,
// byte selects, single-cycle ack) PLUS a host byte-write port. The host loads
// firmware through the write port (from FW_WRITE) while the core is halted; the
// core then fetches/loads from the Wishbone port. Because loading happens with
// the core in reset, the two paths never write at the same time -- a single
// clocked block with host-write priority keeps it a clean single-driver RAM.
//
// This replaces servant_ram in our serv_soc so firmware is uploadable instead of
// baked in at synthesis via $readmemh.

`default_nettype none

module serv_ram_hw #(
    parameter depth = 16384,
    parameter aw    = $clog2(depth)
)(
    // Wishbone port (core)
    input  wire          i_wb_clk,
    input  wire          i_wb_rst,
    input  wire [aw-1:2] i_wb_adr,
    input  wire [31:0]   i_wb_dat,
    input  wire [3:0]    i_wb_sel,
    input  wire          i_wb_we,
    input  wire          i_wb_cyc,
    output reg  [31:0]   o_wb_rdt,
    output reg           o_wb_ack,
    // host byte-write port (same clock; used while the core is halted)
    input  wire          i_host_we,
    input  wire [aw-1:0] i_host_adr,
    input  wire [7:0]    i_host_dat
);
    reg [31:0] mem [0:depth/4-1] /* verilator public */;

    wire [3:0]    wbwe    = {4{i_wb_we & i_wb_cyc}} & i_wb_sel;
    wire [aw-3:0] wbaddr  = i_wb_adr[aw-1:2];
    wire [aw-3:0] hostw   = i_host_adr[aw-1:2];

    always @(posedge i_wb_clk)
        if (i_wb_rst) o_wb_ack <= 1'b0;
        else          o_wb_ack <= i_wb_cyc & !o_wb_ack;

    always @(posedge i_wb_clk) begin
        if (i_host_we) begin                       // host firmware load (byte)
            case (i_host_adr[1:0])
                2'd0: mem[hostw][7:0]   <= i_host_dat;
                2'd1: mem[hostw][15:8]  <= i_host_dat;
                2'd2: mem[hostw][23:16] <= i_host_dat;
                2'd3: mem[hostw][31:24] <= i_host_dat;
            endcase
        end else begin                             // core (Wishbone) writes
            if (wbwe[0]) mem[wbaddr][7:0]   <= i_wb_dat[7:0];
            if (wbwe[1]) mem[wbaddr][15:8]  <= i_wb_dat[15:8];
            if (wbwe[2]) mem[wbaddr][23:16] <= i_wb_dat[23:16];
            if (wbwe[3]) mem[wbaddr][31:24] <= i_wb_dat[31:24];
        end
        o_wb_rdt <= mem[wbaddr];
    end
endmodule

`default_nettype wire
