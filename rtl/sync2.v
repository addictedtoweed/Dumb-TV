// sync2.v  -- two-flop synchronizer for a bus crossing into `clk`'s domain.
//
// Used for the OSD configuration (window/alpha/enable): these values are
// quasi-static -- the host changes them rarely over UART -- so a plain 2-flop
// synchronizer per bit is sufficient. The only visible effect of multi-bit
// incoherence during the rare update is at most one frame showing a partially
// updated OSD position, which is cosmetically invisible. (Pixel data that must
// be bit-coherent crosses through the dual-clock block RAM instead.)

`default_nettype none

module sync2 #(
    parameter W = 1
)(
    input  wire         clk,
    input  wire [W-1:0] d,
    output reg  [W-1:0] q
);
    reg [W-1:0] meta;
    always @(posedge clk) begin
        meta <= d;
        q    <= meta;
    end
endmodule

`default_nettype wire
