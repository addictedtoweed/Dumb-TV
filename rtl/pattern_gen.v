// pattern_gen.v
//
// Stand-in for the live video stream. Produces a simple gradient so the
// testbench can predict every pixel exactly:
//     R = x[7:0]   G = y[7:0]   B = 0x40
// In the real product this block is REPLACED by the DisplayPort RX output.

`default_nettype none

module pattern_gen #(
    parameter CW = 12
)(
    input  wire [CW-1:0] x,
    input  wire [CW-1:0] y,
    input  wire          de,
    output wire [7:0]    r,
    output wire [7:0]    g,
    output wire [7:0]    b
);
    assign r = de ? x[7:0] : 8'h00;
    assign g = de ? y[7:0] : 8'h00;
    assign b = de ? 8'h40  : 8'h00;
endmodule

`default_nettype wire
