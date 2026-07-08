// fifo.v  -- simple synchronous FIFO (first-word-fall-through).
//
// Buffers a byte stream so the command mux can hold a whole frame from one
// source while it services the other. `dout` is valid whenever !empty; assert
// `pop` to advance. Depth must be a power of two.

`default_nettype none

module fifo #(
    parameter W     = 8,
    parameter DEPTH = 512,
    parameter AW    = $clog2(DEPTH)
)(
    input  wire         clk,
    input  wire         rst,
    input  wire         push,
    input  wire [W-1:0] din,
    input  wire         pop,
    output wire [W-1:0] dout,
    output wire         empty,
    output wire         full
);
    reg [W-1:0] mem [0:DEPTH-1];
    reg [AW:0]  wptr, rptr;          // extra MSB distinguishes full from empty

    assign empty = (wptr == rptr);
    assign full  = (wptr[AW-1:0] == rptr[AW-1:0]) && (wptr[AW] != rptr[AW]);
    assign dout  = mem[rptr[AW-1:0]];

    always @(posedge clk) begin
        if (rst) begin
            wptr <= 0;
            rptr <= 0;
        end else begin
            if (push && !full)  begin mem[wptr[AW-1:0]] <= din; wptr <= wptr + 1'b1; end
            if (pop  && !empty) rptr <= rptr + 1'b1;
        end
    end
endmodule

`default_nettype wire
