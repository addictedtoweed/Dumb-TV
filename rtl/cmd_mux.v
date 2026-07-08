// cmd_mux.v  -- two-source command arbiter for cmd_parser.
//
// Lets two byte-stream command sources share one cmd_parser: the physical host
// UART (source 0) and an internal source (source 1 -- e.g. the SERV core's
// bit-banged UART). Each source is buffered in a FIFO so neither drops bytes
// while the other is serviced.
//
// Arbitration is FRAME-ATOMIC and robust to garbage: while idle, the mux feeds
// whichever source has a byte (source 0 priority) but only LOCKS onto a source
// when the fed byte is a SYNC (0xA5) -- i.e. a real frame is starting. Non-sync
// bytes are fed and harmlessly discarded by the parser (which stays in S_SYNC),
// then the mux re-arbitrates -- so an internal source idling / emitting junk
// (e.g. a GPIO before firmware raises it) can never starve the host. Once
// locked, the source keeps the parser until the frame + response complete, and
// the response is routed back to it.

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
    localparam [7:0] SYNC = 8'hA5;

    wire [7:0] f0_dout, f1_dout;
    wire       f0_empty, f1_empty, f0_full, f1_full;

    reg        locked;    // a frame is in progress on `granted`
    reg        granted;   // which source owns the parser (0/1)

    // while unlocked, service whichever source has data (source 0 priority)
    wire       sel      = ~f0_empty ? 1'b0 : 1'b1;
    wire       cur      = locked ? granted : sel;
    wire       cur_empty = cur ? f1_empty : f0_empty;
    wire [7:0] cur_dout  = cur ? f1_dout : f0_dout;
    wire       feed      = p_rx_ready && !cur_empty;

    wire pop0 = feed && (cur == 1'b0);
    wire pop1 = feed && (cur == 1'b1);

    fifo #(.DEPTH(FIFO_DEPTH)) u_f0 (
        .clk(clk), .rst(rst),
        .push(s0_valid && !f0_full), .din(s0_data),
        .pop(pop0), .dout(f0_dout), .empty(f0_empty), .full(f0_full));
    fifo #(.DEPTH(FIFO_DEPTH)) u_f1 (
        .clk(clk), .rst(rst),
        .push(s1_valid && !f1_full), .din(s1_data),
        .pop(pop1), .dout(f1_dout), .empty(f1_empty), .full(f1_full));

    assign p_rx_data  = cur_dout;
    assign p_rx_valid = feed;

    // route the parser's response back to the current (locked) source
    assign t0_data  = p_tx_data;
    assign t1_data  = p_tx_data;
    assign t0_start = (cur == 1'b0) && p_tx_start;
    assign t1_start = (cur == 1'b1) && p_tx_start;
    assign p_tx_busy = cur ? t1_busy : t0_busy;

    always @(posedge clk) begin
        if (rst) begin
            locked  <= 1'b0;
            granted <= 1'b0;
        end else if (!locked) begin
            // lock only when a real frame starts (a sync byte gets consumed)
            if (feed && cur_dout == SYNC) begin
                locked  <= 1'b1;
                granted <= cur;
            end
        end else if (!p_busy) begin
            locked <= 1'b0;                 // frame + response complete
        end
    end
endmodule

`default_nettype wire
