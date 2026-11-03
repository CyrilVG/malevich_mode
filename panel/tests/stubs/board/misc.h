#include <stdint.h>
static uint32_t fake_clock;
static uint32_t timer_read_time(void) {return ++fake_clock;}
static uint32_t timer_from_us(uint32_t us) {return us*168;}
static int timer_is_before(uint32_t a,uint32_t b) {return (int32_t)(a-b)<0;}
