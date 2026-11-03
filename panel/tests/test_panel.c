#include <stdio.h>
#include "../src/malevich_panel.c"
static void run(unsigned n) {while(n--) {scan_event(&scan_timer); malevich_panel_task();}}
static void sample(unsigned value,unsigned n) {input_value=value;run(n);}
static void clear_events(void) {read_seq=write_seq=0; decoder=0;raw=15;}
int main(void) {
    malevich_panel_init();
    run(12000); assert(initialized && !visible && !online && !drawing);
    // Full frame required, boot logo completed >5s ago.
    uint32_t start[]={2,239,0}; command_panel_start(start);
    frame_mask=0xfffffffe;run(10);assert(!visible);
    frame_mask=0xffffffff;run(70);assert(visible);
    clear_events();
    // Two half detents per complete quadrature cycle, bounce included.
    unsigned cw[]={15,13,15,13,12,14,12,14,15};
    for(unsigned i=0;i<sizeof(cw)/sizeof(cw[0]);i++) sample(cw[i],1);
    assert(write_seq==2 && events[0].action==1 && events[1].action==1);
    clear_events();
    unsigned ccw[]={15,14,12,13,15};
    for(unsigned i=0;i<5;i++) sample(ccw[i],1);
    assert(write_seq==2 && events[0].action==2 && events[1].action==2);
    // Ordered direction changes retained, not net displacement.
    for(unsigned i=0;i<9;i++) sample(cw[i],1);
    assert(write_seq==4 && events[2].action==1);
    clear_events(); steps=4;
    for(unsigned i=0;i<9;i++) sample(cw[i],1);
    assert(write_seq==1);steps=2;
    clear_events();sample(11,4);sample(15,4);assert(!write_seq);
    sample(11,20);sample(15,20);assert(write_seq==1 && events[0].action==3);
    clear_events();heartbeat=tick;
    sample(11,1650);sample(15,20);assert(write_seq==1 && events[0].action==4);
    // Acknowledgement window rejects future ACK; retries preserve events.
    uint32_t ack[]={0};command_panel_query(ack);assert(read_seq==0);
    ack[0]=2;command_panel_query(ack);assert(read_seq==0);
    ack[0]=1;command_panel_query(ack);assert(read_seq==1);
    // Timeout, complete splash, quick reconnect, five-second hold.
    heartbeat=tick;run(2100);assert(!online && !visible && !drawing);
    uint32_t appearance=shown_at;command_panel_query(ack);
    while(tick-appearance<9999) {heartbeat=tick;run(1);assert(!visible);}
    heartbeat=tick;run(1);assert(visible);
    // Emergency shutdown remains offline; timers and splash resume.
    malevich_panel_shutdown();run(100);assert(!online && !visible && !drawing);
    // FIFO is bounded and overflow diagnostic increments without corruption.
    clear_events();for(unsigned i=0;i<QSIZE+3;i++) enqueue(1);
    assert(write_seq==QSIZE && overflow==3);
    puts("PASS: actual MCU code: quadrature/bounce/press/long/ACK/timeout/dwell/shutdown/FIFO");
}
