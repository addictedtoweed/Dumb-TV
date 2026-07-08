// cmd_mux.v  -- two-source command arbiter for cmd_parser.
//
// Lets two byte-stream command sources share one cmd_parser: the physical host
// UART (source 0) and an internal source (source 1 -- e.g. the SERV core's
// UART). Arbitration is FRAME-ATOMIC: when the parser is idle, whichever source
// has a buffered byte is granted (source 0 priority), and it keeps the parser
// until the whole frame + its response complete; then it re-arbitrates. The
// parser's TX response is routed back to the granted source, so each requester
// gets its own ACK.
//
// Each source is buffered in a FIFO so the non-granted source never drops bytes
// while the other is being serviced. The parser's rx_ready gates feeding so no
// byte is delivered while the parser is mid-execution.

`default_nettype none

module cmd_mux #(
    parameter FIFO_DEPTH = 512
)(
    input  wire        clk,
    input  wire        rst,
    // source 0 (physical host UART)
    input  wire [7:0]  s0_data,
    input  wire        s0_valid,
    output wire [7:0]  t0_data,
    output wire        t0_start,
    input  wire        t0_busy,
    // source 1 (internal / SERV)
    input  wire [7:0]  s1_data,
    input  wire        s1_valid,
    output wire [7:0]  t1_data,
    output wire        t1_start,
    input  wire        t1_busy,
    // to/from the shared parser
    output wire [7:0]  p_rx_data,
    output wire        p_rx_valid,
    input  wire        p_rx_ready,
    input  wire [7:0]  p_tx_data,
    input  wire        p_tx_start,
    output wire        p_tx_busy,
    input  wire        p_busy
);
    wire [7:0] f0_dout, f1_dout;
    wire       f0_empty, f1_empty, f0_full, f1_full;

    reg        granted;   // which source owns the parser (0/1)
    reg        active;    // a source is currently being serviced
    reg        started;   // parser has gone busy since the grant

    wire pop0 = active && !granted && p_rx_ready && !f0_empty;
    wire pop1 = active &&  granted && p_rx_ready && !f1_empty;

    fifo #(.DEPTH(FIFO_DEPTH)) u_f0 (
        .clk(clk), .rst(rst),
        .push(s0_valid && !f0_full), .din(s0_data),
        .pop(pop0), .dout(f0_dout), .empty(f0_empty), .full(f0_full));
    fifo #(.DEPTH(FIFO_DEPTH)) u_f1 (
        .clk(clk), .rst(rst),
        .push(s1_valid && !f1_full), .din(s1_data),
        .pop(pop1), .dout(f1_dout), .empty(f1_empty), .full(f1_full));

    // feed the granted source into the parser (one byte per accepted cycle)
    assign p_rx_data  = granted ? f1_dout : f0_dout;
    assign p_rx_valid = granted ? pop1 : pop0;

    // route the parser's response back to the granted source
    assign t0_data  = p_tx_data;
    assign t1_data  = p_tx_data;
    assign t0_start = active && !granted && p_tx_start;
    assign t1_start = active &&  granted && p_tx_start;
    assign p_tx_busy = granted ? t1_busy : t0_busy;

    always @(posedge clk) begin
        if (rst) begin
            active  <= 1'b0;
            granted <= 1'b0;
            started <= 1'b0;
        end else if (!active) begin
            if (!p_busy) begin                      // parser idle -> grant a source
                if (!f0_empty)      begin active <= 1'b1; granted <= 1'b0; started <= 1'b0; end
                else if (!f1_empty) begin active <= 1'b1; granted <= 1'b1; started <= 1'b0; end
            end
        end else begin
            if (p_busy)             started <= 1'b1;              // frame started
            if (started && !p_busy) begin active <= 1'b0; started <= 1'b0; end  // frame+resp done
        end
    end
endmodule

`default_nettype wire
