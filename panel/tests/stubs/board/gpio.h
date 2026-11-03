#include <stdint.h>
struct gpio_out { int pin; };
struct gpio_in { int pin; };
static unsigned input_value=15, input_index;
static struct gpio_out gpio_out_setup(int p,int v) { return (struct gpio_out){p}; }
static struct gpio_in gpio_in_setup(int p,int v) { return (struct gpio_in){p}; }
static void gpio_out_write(struct gpio_out p,int v) { if(p.pin==55 && !v) input_index=0; }
static int gpio_in_read(struct gpio_in p) { return (input_value >> (7-(input_index++ % 8))) & 1; }
