// Fixed PICASO SSD1309 / inverted-clock HC165 panel. GPL-3.0-or-later.
#include <string.h>
#include "board/gpio.h"
#include "board/irq.h"
#include "board/misc.h"
#include "command.h"
#include "sched.h"
#include "malevich_logo.h"

DECL_CONSTANT_STR("RESERVE_PINS_malevich_panel", "PD5,PD6,PD7,PB3,PB4,PB5");
DECL_CONSTANT("MALEVICH_PANEL_VERSION", 1);
#define PIN(port, n) (((port)-'A') * 16 + (n))
#define QSIZE 256
struct panel_event { uint32_t tick; uint8_t action; };
static struct panel_event events[QSIZE];
static struct gpio_out cs, rst, dc, clk, mosi;
static struct gpio_in miso;
static struct timer scan_timer;
static struct task_wake wake;
static uint8_t framebuffer[1024];
static uint32_t frame_mask, tick, heartbeat, shown_at, read_seq, write_seq;
static uint32_t overflow, invalid, max_scan_ticks, last_scan;
static uint8_t online, visible, initialized, raw, decoder, steps = 2;
static uint8_t candidate, button, stable, held, long_sent;
static uint32_t pressed_at;
static uint8_t contrast = 239, invert, dirty = 1;
static uint16_t draw_pos;
static uint8_t drawing, drawing_visible;

// Same bounce-resistant state machines as Klipper buttons.py.
static const uint8_t half_steps[6][4] = {
    {3,2,1,0}, {0x23,0,1,0}, {0x13,2,0,0},
    {3,5,4,0}, {3,3,4,0x10}, {3,5,3,0x20}
};
static const uint8_t full_steps[7][4] = {
    {0,2,4,0}, {3,0,1,0x10}, {3,2,0,0}, {3,2,1,0},
    {6,0,4,0}, {6,5,0,0x20}, {6,5,4,0}
};

static void delay_half(void) {
    uint32_t end = timer_read_time() + timer_from_us(1) / 2;
    while (timer_is_before(timer_read_time(), end)) ;
}
// CS is released after each byte. Scan ISR may safely run BETWEEN bytes,
// never during a byte. PD7 is /PL for HC165 as well as OLED D/C.
static void lcd_byte(uint8_t data, uint8_t value) {
    irqstatus_t flags = irq_save();
    gpio_out_write(cs, 1);
    gpio_out_write(clk, 0);
    gpio_out_write(dc, data);
    gpio_out_write(cs, 0);
    for (uint8_t bit = 0; bit < 8; bit++) {
        gpio_out_write(mosi, value & 0x80);
        delay_half();
        gpio_out_write(clk, 1);
        delay_half();
        gpio_out_write(clk, 0);
        value <<= 1;
    }
    gpio_out_write(cs, 1);
    gpio_out_write(dc, 1);
    irq_restore(flags);
}
static uint8_t read_hc165(void) {
    gpio_out_write(cs, 1);
    gpio_out_write(clk, 0);
    gpio_out_write(dc, 0);
    delay_half();
    gpio_out_write(dc, 1);
    delay_half();
    uint8_t value = 0;
    for (uint8_t bit = 0; bit < 8; bit++) {
        // HC165 CP is inverted: sample Q7 BEFORE MCU falling edge.
        value = (value << 1) | !!gpio_in_read(miso);
        gpio_out_write(clk, 1);
        delay_half();
        gpio_out_write(clk, 0);
        delay_half();
    }
    return value;
}
static void enqueue(uint8_t action) {
    if (write_seq - read_seq == QSIZE) { overflow++; return; }
    events[write_seq % QSIZE].tick = tick;
    events[write_seq % QSIZE].action = action;
    write_seq++;
}
static void input_sample(uint8_t value) {
    uint8_t ab = value & 3;
    if (((raw ^ value) & 3) == 3) { invalid++; decoder = 0; }
    decoder = steps == 2 ? half_steps[decoder & 15][ab]
                         : full_steps[decoder & 15][ab];
    if (decoder & 0x10) enqueue(1);
    if (decoder & 0x20) enqueue(2);
    uint8_t current = !(value & 4);
    if (candidate != current) { candidate = current; stable = 0; }
    else if (stable < 10) stable++; // 5 ms stable press/release
    if (stable == 10 && button != candidate) {
        button = candidate;
        if (button) { held = 1; long_sent = 0; pressed_at = tick; }
        else if (held) {
            if (!long_sent) enqueue(3);
            held = 0;
        }
    }
    if (held && !long_sent && tick - pressed_at >= 1600) {
        enqueue(4); long_sent = 1;
    }
}
static uint_fast8_t scan_event(struct timer *t) {
    uint32_t now = timer_read_time(), interval = now - last_scan;
    if (interval > max_scan_ticks) max_scan_ticks = interval;
    last_scan = now;
    tick++;
    uint8_t value = read_hc165();
    if (online && visible) input_sample(value);
    else {
        decoder = 0; held = 0; stable = 0;
        button = candidate = !(value & 4);
    }
    raw = value;
    if (online && tick - heartbeat >= 2000) {
        online = 0;
        if (visible) { visible = 0; dirty = 1; }
        read_seq = write_seq;
    }
    sched_wake_task(&wake);
    t->waketime += timer_from_us(500);
    return SF_RESCHEDULE;
}
void malevich_panel_init(void) {
    cs = gpio_out_setup(PIN('D',5), 1);
    rst = gpio_out_setup(PIN('D',6), 0);
    dc = gpio_out_setup(PIN('D',7), 1);
    clk = gpio_out_setup(PIN('B',3), 0);
    mosi = gpio_out_setup(PIN('B',5), 0);
    miso = gpio_in_setup(PIN('B',4), 0);
    scan_timer.func = scan_event;
    last_scan = timer_read_time();
    scan_timer.waketime = last_scan + timer_from_us(500);
    sched_add_timer(&scan_timer);
}
DECL_INIT(malevich_panel_init);

void malevich_panel_task(void) {
    if (!sched_check_wake(&wake)) return;
    if (!initialized) {
        if (tick < 40) return; // reset low for 20 ms
        gpio_out_write(rst, 1);
        if (tick < 80) return; // 20 ms settling, nonblocking
        const uint8_t init[] = {0xae,0xd5,0x80,0xa8,0x3f,0xd3,0,0x40,
            0x8d,0x14,0x20,2,0xa1,0xc8,0xda,0x12,0x81,239,
            0xd9,0xa1,0xdb,0,0x2e,0xa4,0xa6,0xaf};
        for (uint8_t i=0; i<sizeof(init); i++) lcd_byte(0,init[i]);
        initialized = 1;
    }
    // Minimum FIVE seconds after the complete logo becomes visible.
    if (!visible && online && frame_mask == 0xffffffffu
        && !drawing && !dirty && tick - shown_at >= 10000) {
        visible = 1; dirty = 1;
    }
    if (drawing && drawing_visible != visible) drawing = 0;
    if (!drawing) {
        if (!dirty) return;
        dirty = 0; drawing = 1; draw_pos = 0; drawing_visible = visible;
        lcd_byte(0,0x81); lcd_byte(0,visible ? contrast : 239);
        lcd_byte(0,visible && invert ? 0xa7 : 0xa6);
    }
    uint8_t page = draw_pos >> 7, col = draw_pos & 127;
    lcd_byte(0,0xb0 | page); lcd_byte(0,0x10 | (col >> 4));
    lcd_byte(0,col & 15);
    for (uint8_t i=0;i<16;i++,draw_pos++)
        lcd_byte(1, drawing_visible ? framebuffer[draw_pos] : malevich_logo[draw_pos]);
    if (draw_pos == 1024) {
        drawing = 0;
        if (!drawing_visible) shown_at = tick;
    }
}
DECL_TASK(malevich_panel_task);

void malevich_panel_shutdown(void) {
    online = visible = 0; dirty = 1; drawing = 0;
    frame_mask = 0; read_seq = write_seq; held = 0;
    gpio_out_write(cs, 1); gpio_out_write(dc, 1); gpio_out_write(clk, 0);
    last_scan = timer_read_time();
    scan_timer.waketime = last_scan + timer_from_us(500);
    sched_add_timer(&scan_timer); // Klipper removed all user timers.
}
DECL_SHUTDOWN(malevich_panel_shutdown);

void command_panel_start(uint32_t *args) {
    if (args[0] != 2 && args[0] != 4) shutdown("Invalid panel encoder steps");
    irqstatus_t f = irq_save();
    steps = args[0]; contrast = args[1]; invert = !!args[2];
    read_seq = write_seq = 0; frame_mask = 0; decoder = held = 0;
    heartbeat = tick; online = 1;
    irq_restore(f);
}
DECL_COMMAND(command_panel_start, "panel_start steps=%c contrast=%c invert=%c");
void command_panel_frame(uint32_t *args) {
    uint16_t offset = args[0]; uint8_t len = args[1];
    uint8_t *data = command_decode_ptr(args[2]);
    if (offset > 992 || offset % 32 || len != 32)
        shutdown("Invalid panel framebuffer chunk");
    memcpy(framebuffer + offset, data, 32);
    frame_mask |= 1u << (offset / 32);
    if (visible) dirty = 1;
}
DECL_COMMAND(command_panel_frame, "panel_frame offset=%hu data=%*s");
void command_panel_query(uint32_t *args) {
    uint8_t payload[40], count = 0;
    irqstatus_t f = irq_save();
    uint32_t ack = args[0];
    if (ack - read_seq <= write_seq - read_seq) read_seq = ack;
    heartbeat = tick; online = 1;
    uint32_t seq = read_seq, now = tick;
    while (seq != write_seq && count < 8) {
        struct panel_event *e = &events[seq++ % QSIZE];
        uint8_t *p = payload + count++ * 5;
        p[0] = e->action;
        for (uint8_t i=0;i<4;i++) p[i+1] = e->tick >> (i*8);
    }
    uint32_t base = read_seq;
    irq_restore(f);
    sendf("panel_events seq=%u tick=%u data=%*s",base,now,count*5,payload);
}
DECL_COMMAND(command_panel_query, "panel_query ack=%u");
void command_panel_status(uint32_t *args) {
    sendf("panel_status raw=%c online=%c visible=%c overflow=%u invalid=%u max_scan_ticks=%u",
          raw, online, visible, overflow, invalid, max_scan_ticks);
}
DECL_COMMAND_FLAGS(command_panel_status, HF_IN_SHUTDOWN, "panel_get_status");
