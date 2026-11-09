/* Malevich board autodetection v0.6.0 - STM32F407VE, 16MHz HSI
 * Confirmed board wiring:
 * XL: PB10=USART3 single-wire PDN_UART; PC3=bank; PE14=VCC_IO rail
 *     7x TMC2209 (bank1: 4/3/2/1 addr0/1/2/3, bank0: 5/6/7 addr0/1/3).
 * X:  PB10=SPI SCK; PC3=MOSI; PC2=MISO; PE11/12/13/14=CSN X/Y/Z/E.
 * UART-first, SPI-second: never create SPI clock on confirmed XL.
 * Only IOIN reads: 2209 addr 0x06 / ver 0x21; 2130 addr 0x04 / ver 0x11.
 * No automatic bus activity after MCU reset: E enables PE14 HIGH (45s cap),
 * A then Y performs a single complete automatic detection. No retry till reset.
 * Motors/heaters must be physically disconnected for experimental use.
 * Does not guarantee electrical safety if driver outputs contend with MCU.
 * FT232R console UART5 PC12/PD2 115200 8N1.
 */
#include <stdint.h>
#include <stddef.h>
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define RCC          0x40023800u
#define RCC_AHB1ENR  REG(RCC+0x30u)
#define RCC_APB1ENR  REG(RCC+0x40u)
#define GPIOB 0x40020400u
#define GPIOC 0x40020800u
#define GPIOD 0x40020C00u
#define GPIOE 0x40021000u
#define USART3 0x40004800u
#define UART5  0x40005000u
#define USR(u)       REG((u)+0x00u)
#define UDR(u)       REG((u)+0x04u)
#define UBRR(u)      REG((u)+0x08u)
#define UCR1(u)      REG((u)+0x0Cu)
#define UCR2(u)      REG((u)+0x10u)
#define UCR3(u)      REG((u)+0x14u)
#define USART_ERR    ((1u<<1)|(1u<<2)|(1u<<3))
#define USART_RXNE   (1u<<5)
#define USART_TC     (1u<<6)
#define USART_TXE    (1u<<7)
#define USART_UE     (1u<<13)
#define USART_TE     (1u<<3)
#define USART_RE     (1u<<2)
#define USART_HDSEL  (1u<<3)
#define TIM2_CR1     REG(0x40000000u)
#define TIM2_EGR     REG(0x40000014u)
#define TIM2_CNT     REG(0x40000024u)
#define TIM2_PSC     REG(0x40000028u)
#define TIM2_ARR     REG(0x4000002Cu)
#define GPIO_IN 0u
#define GPIO_OUT 1u
#define GPIO_AF 2u
#define PULL_NONE 0u
#define PULL_UP 1u
#define POWER_MAX_US 45000000u
#define NUM_CHIPS 7u
#define NUM_SPEEDS 2u
#define REPEATS 2u
#define MAGIC 0x41443036u /* AD06 */
#define RESULT_UNKNOWN 0u
#define RESULT_X 1u
#define RESULT_XL 2u

static void gpio_set(uint32_t port,unsigned pin,unsigned mode,unsigned od,unsigned pull,unsigned af)
{
    unsigned s=pin*2u;
    REG(port+0x00u)&=~(3u<<s);
    REG(port+0x04u)=(REG(port+0x04u)&~(1u<<pin))|((od&1u)<<pin);
    REG(port+0x08u)=(REG(port+0x08u)&~(3u<<s))|(1u<<s);
    REG(port+0x0Cu)=(REG(port+0x0Cu)&~(3u<<s))|((pull&3u)<<s);
    if(mode==GPIO_AF){
        uint32_t a=port+(pin<8u?0x20u:0x24u);
        unsigned t=(pin&7u)*4u;
        REG(a)=(REG(a)&~(15u<<t))|((af&15u)<<t);
    }
    if(mode!=GPIO_IN)REG(port+0x00u)=(REG(port+0x00u)&~(3u<<s))|(mode<<s);
}
static void pin_write(uint32_t port,unsigned pin,unsigned high)
{ REG(port+0x18u)=high?(1u<<pin):(1u<<(pin+16u)); }
static unsigned pin_read(uint32_t port,unsigned pin)
{ return (REG(port+0x10u)>>pin)&1u; }
static uint32_t ticks(void){return TIM2_CNT;}
static unsigned expired(uint32_t start,uint32_t usec)
{return (uint32_t)(ticks()-start)>=usec;}
static void delay_us(unsigned usec)
{uint32_t start=ticks();while(!expired(start,usec))__asm__ volatile("nop");}
static void delay_ms(unsigned ms){while(ms--)delay_us(1000u);}
static void tx(char c)
{
    uint32_t start=ticks();
    while(!(USR(UART5)&USART_TXE))if(expired(start,10000u))return;
    UDR(UART5)=(uint8_t)c;
}
static void say(const char *s){while(*s){if(*s=='\n')tx('\r');tx(*s++);}}
static void hex8(unsigned v){tx("0123456789ABCDEF"[(v>>4)&15u]);tx("0123456789ABCDEF"[v&15u]);}
static void hex32(uint32_t v){for(int i=28;i>=0;i-=4)tx("0123456789ABCDEF"[(v>>i)&15u]);}
static void dec(unsigned v)
{
    char b[11];unsigned n=0;
    do{b[n++]=(char)('0'+(v%10u));v/=10u;}while(v&&n<sizeof b);
    while(n)tx(b[--n]);
}
static int console_rx(void){return (USR(UART5)&USART_RXNE)?(int)(UDR(UART5)&255u):-1;}

struct uart_sample {
    uint32_t tried,got,ioin,sr,flags,tx_err;
    uint8_t raw[8];
};
struct chip {
    uint32_t driver,bank,addr,ok,baud,ioin;
    struct uart_sample samples[NUM_SPEEDS][REPEATS];
};
struct spi_chip {
    uint32_t cs_pin,tried,ok,first,second,third;
};
struct report {
    uint32_t magic,state,result,error,started,done;
    uint32_t power_on,power_started,power_count,power_reason,power_readback;
    uint32_t passive_count,initial_pb10,bank1_pb10,bank0_pb10,bank1_pc3,bank0_pc3;
    uint32_t uart_candidate_reads,uart_confirmed,spi_confirmed,spi_clock_fault;
    struct chip chips[NUM_CHIPS];
    struct spi_chip spi[3];
};
static volatile struct report g_report;
static const uint8_t chip_num[NUM_CHIPS]={4,3,2,1,5,6,7};
static const uint8_t bank_num[NUM_CHIPS]={1,1,1,1,0,0,0};
static const uint8_t node_addr[NUM_CHIPS]={0,1,2,3,0,1,3};
static const uint8_t spi_cs_pins[3]={11,12,13};
static const uint32_t baud_rates[NUM_SPEEDS]={57600u,115200u};

static void uart_disable(void){UCR1(USART3)=0u;}
static void release_bus(void)
{
    uart_disable();
    pin_write(GPIOB,10,1u);
    gpio_set(GPIOB,10,GPIO_IN,1,PULL_UP,0);
    gpio_set(GPIOC,3,GPIO_IN,0,PULL_NONE,0);
}
static void idle_csn(void)
{
    /* On X: deassert CSN_X/Y/Z. On XL: STEP3/2/1 -> HIGH once.
     * Physical motor disconnect REQUIRED for the test. */
    for(unsigned i=0;i<3u;++i){
        unsigned pin=spi_cs_pins[i];
        pin_write(GPIOE,pin,1u);
        gpio_set(GPIOE,pin,GPIO_OUT,0,PULL_UP,0); /* push-pull HIGH, X CSN safely deasserted */
    }
}
static void release_csn(unsigned is_x)
{
    for(unsigned i=0;i<3u;++i){
        unsigned pin=spi_cs_pins[i];
        pin_write(GPIOE,pin,1u);
        gpio_set(GPIOE,pin,GPIO_IN,1,is_x?PULL_UP:PULL_NONE,0);
    }
}
static void power_off(unsigned reason)
{
    /* X: PE14 is CSN_E, weak pullup remains. XL: VCC_IO completely released.
     * Unknown: assume XL and do not weakly back-power VCC_IO. */
    gpio_set(GPIOE,14,GPIO_IN,0,g_report.result==RESULT_X?PULL_UP:PULL_NONE,0);
    g_report.power_on=0u;
    g_report.power_reason=reason;
}
static unsigned power_ok(void)
{
    if(!g_report.power_on)return 0u;
    g_report.power_readback=pin_read(GPIOE,14);
    if(!g_report.power_readback){g_report.error=5u;power_off(5u);return 0u;}
    if(expired(g_report.power_started,POWER_MAX_US)){
        g_report.error=6u;power_off(6u);return 0u;
    }
    return 1u;
}
static unsigned power_enable(void)
{
    if(g_report.power_count||g_report.state!=0u)return 0u;
    ++g_report.power_count;
    pin_write(GPIOE,14,1u); /* preload HIGH before enabling output */
    gpio_set(GPIOE,14,GPIO_OUT,0,PULL_NONE,0);
    delay_ms(100u);
    if(!pin_read(GPIOE,14)){
        g_report.error=5u;power_off(5u);return 0u;
    }
    g_report.power_readback=1u;
    g_report.power_on=1u;
    g_report.power_started=ticks();
    return 1u;
}
static void init_hw(void)
{
    RCC_AHB1ENR|=(1u<<1)|(1u<<2)|(1u<<3)|(1u<<4);
    RCC_APB1ENR|=(1u<<0)|(1u<<18)|(1u<<20);
    (void)RCC_AHB1ENR;(void)RCC_APB1ENR;
    TIM2_CR1=0;TIM2_PSC=15u;TIM2_ARR=0xFFFFFFFFu;
    TIM2_EGR=1u;TIM2_CNT=0u;TIM2_CR1=1u;
    g_report.magic=MAGIC;
    for(unsigned i=0;i<NUM_CHIPS;++i){
        g_report.chips[i].driver=chip_num[i];
        g_report.chips[i].bank=bank_num[i];
        g_report.chips[i].addr=node_addr[i];
    }
    for(unsigned i=0;i<3u;++i)g_report.spi[i].cs_pin=spi_cs_pins[i];
    pin_write(GPIOC,12,1u);
    gpio_set(GPIOC,12,GPIO_AF,0,PULL_UP,8u);
    gpio_set(GPIOD,2,GPIO_AF,0,PULL_UP,8u);
    UCR1(UART5)=0u;UCR2(UART5)=0u;UCR3(UART5)=0u;
    UBRR(UART5)=139u;
    UCR1(UART5)=USART_UE|USART_TE|USART_RE;
    release_bus();
    release_csn(0u);
    power_off(0u);
}
static void passive(void)
{
    if(g_report.state>=2u)return;
    release_bus();delay_ms(20u);
    g_report.initial_pb10=pin_read(GPIOB,10);
    pin_write(GPIOC,3,1u);gpio_set(GPIOC,3,GPIO_OUT,0,PULL_NONE,0);
    delay_ms(25u);
    g_report.bank1_pc3=pin_read(GPIOC,3);
    g_report.bank1_pb10=pin_read(GPIOB,10);
    pin_write(GPIOC,3,0u);delay_ms(25u);
    g_report.bank0_pc3=pin_read(GPIOC,3);
    g_report.bank0_pb10=pin_read(GPIOB,10);
    release_bus();++g_report.passive_count;
}
static void passive_print(void)
{
    say("PASSIVE runs=");dec(g_report.passive_count);
    say(" PB10=");dec(g_report.initial_pb10);
    say(" B1 PC3=");dec(g_report.bank1_pc3);
    say(" PB10=");dec(g_report.bank1_pb10);
    say(" B0 PC3=");dec(g_report.bank0_pc3);
    say(" PB10=");dec(g_report.bank0_pb10);say("\n");
}
static uint8_t crc_tmc(const uint8_t *buf,unsigned count)
{
    uint8_t crc=0u;
    for(unsigned i=0;i<count;++i)for(unsigned bit=0;bit<8u;++bit){
        unsigned x=((crc>>7)^(buf[i]>>bit))&1u;
        crc=(uint8_t)((crc<<1)^(x?7u:0u));
    }
    return crc;
}
static void uart_rx_only(void){UCR1(USART3)=USART_UE|USART_RE;}
static void uart_init(unsigned baud)
{
    uart_disable();
    pin_write(GPIOB,10,1u);
    gpio_set(GPIOB,10,GPIO_AF,1,PULL_UP,7u); /* USART3 1-wire, open-drain */
    UCR2(USART3)=0u;UCR3(USART3)=USART_HDSEL;
    UBRR(USART3)=baud==57600u?278u:139u;
    uart_rx_only();
}
/* flags: bit0 valid CRC+datagram, bit1 VERSION 0x21, bit2 RX error */
static void request_ioin(unsigned addr,volatile struct uart_sample *s)
{
    s->tried=1u;
    uint8_t req[4]={0x05u,(uint8_t)addr,0x06u,0u};
    req[3]=crc_tmc(req,3u);
    uint8_t bytes[8]={0};unsigned n=0;uint32_t faults=0;unsigned timeout=0;
    (void)USR(USART3);(void)UDR(USART3);
    UCR1(USART3)=USART_UE|USART_TE;
    for(unsigned i=0;i<4u;++i){
        uint32_t t=ticks();
        while(!(USR(USART3)&USART_TXE)){
            if(expired(t,4000u)){timeout=1u;goto done;}
        }
        UDR(USART3)=req[i];
    }
    {
        uint32_t t=ticks();
        while(!(USR(USART3)&USART_TC)){
            if(expired(t,4000u)){timeout=1u;goto done;}
        }
    }
    uart_rx_only();
    {
        uint32_t t=ticks();
        while(!expired(t,18000u)){
            uint32_t sr=USR(USART3);
            if(sr&USART_RXNE){
                uint8_t b=(uint8_t)UDR(USART3);
                if(sr&USART_ERR){faults|=sr&USART_ERR;n=0u;continue;}
                if(n==0u && b!=0x05u)continue;
                bytes[n++]=b;
                if(n==8u)break;
            }else if(sr&USART_ERR){
                (void)UDR(USART3);faults|=sr&USART_ERR;n=0u;
            }
        }
    }
 done:
    uart_rx_only();
    s->got=n;s->sr=USR(USART3)|faults;s->tx_err=timeout;
    for(unsigned i=0;i<8u;++i)s->raw[i]=bytes[i];
    if(faults)s->flags|=4u;
    if(n==8u&&bytes[0]==0x05u&&bytes[1]==0xFFu&&
       bytes[2]==0x06u&&bytes[7]==crc_tmc(bytes,7u)){
        s->flags|=1u;
        s->ioin=((uint32_t)bytes[3]<<24)|((uint32_t)bytes[4]<<16)|
                 ((uint32_t)bytes[5]<<8)|bytes[6];
        if((s->ioin>>24)==0x21u)s->flags|=2u;
    }
}
/* Gate line before transmit; if LOW, abort *both* protocols. */
static unsigned uart_gate(unsigned bank)
{
    uart_disable();
    pin_write(GPIOB,10,1u);
    gpio_set(GPIOB,10,GPIO_IN,1,PULL_UP,0);
    pin_write(GPIOC,3,bank);
    gpio_set(GPIOC,3,GPIO_OUT,0,PULL_NONE,0);
    delay_ms(25u);
    if(pin_read(GPIOC,3)!=bank){g_report.error=2u;return 0u;}
    if(!pin_read(GPIOB,10)){g_report.error=1u;return 0u;}
    delay_ms(20u);
    if(!pin_read(GPIOB,10)){g_report.error=1u;return 0u;}
    return 1u;
}
/* one chip, two equal verified reads; returns 1 confirmed, 0 no response, -1 abort */
static int uart_chip(unsigned i,unsigned speed)
{
    volatile struct chip *c=&g_report.chips[i];
    if(!power_ok()){g_report.error=5u;return -1;}
    if(!uart_gate(c->bank))return -1;
    unsigned baud=baud_rates[speed];
    uart_init(baud);
    delay_ms(12u);
    if(!pin_read(GPIOB,10)){g_report.error=1u;return -1;}
    for(unsigned rep=0;rep<REPEATS;++rep){
        volatile struct uart_sample *s=&c->samples[speed][rep];
        request_ioin(c->addr,s);
        ++g_report.uart_candidate_reads;
        if(s->tx_err){g_report.error=4u;return -1;}
        delay_ms(5u);
        if(!pin_read(GPIOB,10)){g_report.error=3u;return -1;}
    }
    volatile struct uart_sample *a=&c->samples[speed][0];
    volatile struct uart_sample *b=&c->samples[speed][1];
    unsigned ok=((a->flags&3u)==3u)&&((b->flags&3u)==3u)&&a->ioin==b->ioin;
    if(ok){c->ok=1u;c->ioin=b->ioin;c->baud=baud;}
    return (int)ok;
}
/* Fast recognition: attempt bank1 addr0 (#4), bank0 addr0 (#5),
 * then bank1 addr1 (#3), bank0 addr1 (#6) at both baudrates. */
static int detect_xl(void)
{
    static const uint8_t first[4]={0,4,1,5};
    say("[UART] XL candidate IOIN 0x06, VERSION 0x21; 57600 then 115200\n");
    for(unsigned speed=0;speed<NUM_SPEEDS;++speed){
        for(unsigned k=0;k<4u;++k){
            unsigned i=first[k];
            int rc=uart_chip(i,speed);
            say(" UART #");dec(g_report.chips[i].driver);
            say(" bank=");dec(g_report.chips[i].bank);
            say(" addr=");dec(g_report.chips[i].addr);
            say(" baud=");dec(baud_rates[speed]);
            say(rc==1?" VERIFIED\n":rc==0?" no reply\n":" ABORT\n");
            if(rc<0)return -1;
            if(rc>0){++g_report.uart_confirmed;return 1;}
        }
    }
    say("[UART] No confirmed TMC2209; SPI candidate next.\n");
    return 0;
}
static int scan_xl(void)
{
    say("[XL] Checking all seven TMC2209 IDs\n");
    for(unsigned speed=0;speed<NUM_SPEEDS;++speed){
        for(unsigned i=0;i<NUM_CHIPS;++i){
            if(g_report.chips[i].ok)continue;
            int rc=uart_chip(i,speed);
            say("  driver #");dec(g_report.chips[i].driver);
            say(" bank=");dec(g_report.chips[i].bank);
            say(" addr=");dec(g_report.chips[i].addr);
            say(" baud=");dec(baud_rates[speed]);
            say(rc==1?" VERIFIED\n":rc==0?" no confirmed reply\n":" ABORT\n");
            if(rc<0)return -1;
        }
    }
    unsigned count=0u;
    for(unsigned i=0;i<NUM_CHIPS;++i)if(g_report.chips[i].ok)++count;
    g_report.uart_confirmed=count;
    return 1;
}
/* TMC2130 SPI MODE 3, 40-bit frame, delayed response 1 frame.
 * SCK PB10 always open-drain, LOW or released; data PC3; MISO PC2.
 * SCK high verified per bit before making further clock pulses. */
static uint8_t spi_byte(uint8_t sent)
{
    uint8_t in=0u;
    for(unsigned n=0;n<8u;++n){
        pin_write(GPIOC,3,(sent&(0x80u>>n))!=0u);
        pin_write(GPIOB,10,0u);
        delay_us(50u);
        pin_write(GPIOB,10,1u);
        delay_us(90u);
        if(!pin_read(GPIOB,10)){g_report.spi_clock_fault=1u;return 0u;}
        in=(uint8_t)((in<<1u)|pin_read(GPIOC,2));
    }
    return in;
}
static uint32_t spi_frame(unsigned cs)
{
    uint8_t bytes[5]={0};
    pin_write(GPIOE,cs,0u);
    delay_us(40u);
    for(unsigned i=0;i<5u&&!g_report.spi_clock_fault;++i)
        bytes[i]=spi_byte(i==0u?0x04u:0u);
    pin_write(GPIOE,cs,1u);
    delay_us(200u);
    return ((uint32_t)bytes[1]<<24)|((uint32_t)bytes[2]<<16)|
           ((uint32_t)bytes[3]<<8)|bytes[4];
}
/* returns 1 for X, 0 no signature, -1 abort. NEVER assert PE14 low. */
static int detect_x(void)
{
    say("[SPI] X candidate IOIN 0x04 via PE11/12/13, PE14 remains HIGH\n");
    uart_disable();
    idle_csn();
    gpio_set(GPIOC,2,GPIO_IN,0,PULL_NONE,0);
    pin_write(GPIOC,3,0u);
    gpio_set(GPIOC,3,GPIO_OUT,0,PULL_NONE,0);
    pin_write(GPIOB,10,1u);
    gpio_set(GPIOB,10,GPIO_OUT,1,PULL_UP,0);
    delay_ms(15u);
    if(!pin_read(GPIOB,10)){g_report.error=7u;return -1;}
    for(unsigned i=0;i<3u;++i){
        volatile struct spi_chip *c=&g_report.spi[i];
        if(!power_ok()){g_report.error=5u;return -1;}
        c->tried=1u;
        c->first=spi_frame(c->cs_pin); /* pipeline warm-up */
        c->second=spi_frame(c->cs_pin);
        c->third=spi_frame(c->cs_pin);
        if(g_report.spi_clock_fault){g_report.error=8u;return -1;}
        c->ok= ((c->second>>24)==0x11u) &&
               ((c->third>>24)==0x11u) &&
               (c->second&(1u<<6)) &&
               (c->third&(1u<<6)) &&
               (c->second==c->third);
        say(" SPI CSN=PE");dec(c->cs_pin);
        say(" IOIN=0x");hex32(c->second);
        say(" /0x");hex32(c->third);
        say(c->ok?" CONFIRMED TMC2130\n":" no verified signature\n");
        if(c->ok){++g_report.spi_confirmed;return 1;}
    }
    return 0;
}
static void report(void)
{
    say("\n=== Malevich AutoDetect v0.6.0 CACHED REPORT ===\n");
    say("state=");dec(g_report.state);
    say(" result=");dec(g_report.result);
    say(" error=");dec(g_report.error);
    say(" power_ON=");dec(g_report.power_on);
    say(" powered_once=");dec(g_report.power_count);
    say(" power_off_reason=");dec(g_report.power_reason);say("\n");
    if(g_report.result==RESULT_XL)say("BOARD: DESIGNER XL / TMC2209 / UART (CONFIRMED)\n");
    else if(g_report.result==RESULT_X)say("BOARD: DESIGNER X / TMC2130 / SPI (CONFIRMED)\n");
    else say("BOARD: UNKNOWN (lack of reply does not identify board)\n");
    say("uart_confirmed=");dec(g_report.uart_confirmed);
    say(" /7  uart_requests=");dec(g_report.uart_candidate_reads);
    say(" spi_confirmed=");dec(g_report.spi_confirmed);
    say(" spi_clock_fault=");dec(g_report.spi_clock_fault);say("\n");
    passive_print();
    for(unsigned i=0;i<NUM_CHIPS;++i){
        volatile struct chip *c=&g_report.chips[i];
        say("UART driver=");dec(c->driver);
        say(" bank=");dec(c->bank);
        say(" addr=");dec(c->addr);
        say(c->ok?" CONFIRMED":" not confirmed");
        if(c->ok){say(" baud=");dec(c->baud);say(" IOIN=0x");hex32(c->ioin);}
        say("\n");
    }
    for(unsigned i=0;i<3u;++i){
        volatile struct spi_chip *c=&g_report.spi[i];
        say("SPI PE");dec(c->cs_pin);
        say(" tried=");dec(c->tried);
        say(" ok=");dec(c->ok);
        if(c->tried){say(" IOIN=0x");hex32(c->second);}
        say("\n");
    }
    if(g_report.error)say("ERROR: 1=PB10 idle LOW, 2=PC3 readback, 3=PB10 after UART, 4=USART timeout, 5=PE14 readback/power, 6=45s timeout, 7=SPI pre-idle LOW, 8=SPI SCK stuck LOW\n");
    if(g_report.state==0u)say("IDLE: E=power, P=passive, then A/Y for one autodetect\n");
    else if(g_report.state==1u)say("ARMED: Y=start, N=cancel\n");
    else say("No additional active scans without power-cycle\n");
    say("E=PE14 ON X=OFF P=passive A=arm Y=one autodetect N=cancel R=report D=raw H=help\n");
}
static void raw_dump(void)
{
    say("\nCACHED UART RAW (NO BUS ACTIVITY)\n");
    for(unsigned i=0;i<NUM_CHIPS;++i){
        volatile struct chip *c=&g_report.chips[i];
        for(unsigned b=0;b<NUM_SPEEDS;++b)for(unsigned r=0;r<REPEATS;++r){
            volatile struct uart_sample *s=&c->samples[b][r];
            if(!s->tried)continue;
            say(" #");dec(c->driver);
            say(" bank=");dec(c->bank);
            say(" addr=");dec(c->addr);
            say(" baud=");dec(baud_rates[b]);
            say(" rep=");dec(r+1u);
            say(" bytes=");dec(s->got);
            say(" flags=0x");hex32(s->flags);
            say(" txerr=");dec(s->tx_err);
            say(" IOIN=0x");hex32(s->ioin);
            say(" raw:");for(unsigned n=0;n<8u;++n){tx(' ');hex8(s->raw[n]);}
            say("\n");
        }
    }
    for(unsigned i=0;i<3u;++i){
        volatile struct spi_chip *c=&g_report.spi[i];
        if(!c->tried)continue;
        say(" SPI PE");dec(c->cs_pin);
        say(" first=0x");hex32(c->first);
        say(" second=0x");hex32(c->second);
        say(" third=0x");hex32(c->third);
        say(" verified=");dec(c->ok);say("\n");
    }
}
static void autodetect_once(void)
{
    if(!power_ok()){say("[ABORT] PE14 not powered\n");return;}
    g_report.state=2u;g_report.started=ticks();g_report.error=0u;
    say("\n[AUTO] Checking XL/UART first, then X/SPI if no UART identity.\n");
    /* XL VCC_IO powered via PE14, X CSN_E deasserted HIGH. */
    idle_csn();delay_ms(25u);
    int xl=detect_xl();
    if(xl>0){
        g_report.result=RESULT_XL;
        (void)scan_xl();
    } else if(xl==0){
        release_bus();delay_ms(25u);
        int x=detect_x();
        if(x>0)g_report.result=RESULT_X;
    }
    /* On every exit, release bus before PE14. No further UART or SPI. */
    release_bus();
    gpio_set(GPIOB,10,GPIO_IN,1,PULL_NONE,0);
    release_csn(g_report.result==RESULT_X);
    power_off(3u);
    g_report.done=ticks();g_report.state=3u;
    report();
}
static void loop(void)
{
    delay_ms(200u);
    say("\n=== Malevich STM32F407 X/XL AutoDetect v0.6.0 ===\n");
    say("E=PE14 HIGH (XL VCC_IO / X CSN_E), 45s MAX. Verify voltage/current.\n");
    say("A then Y: ONE full autodetect. UART first; SPI only if UART failed.\n");
    passive();report();
    for(;;){
        if(g_report.power_on&&!power_ok())say("[AUTO OFF] PE14 released due to timeout/LOW\n");
        int c=console_rx();
        if(c=='R'||c=='r')report();
        else if(c=='D'||c=='d')raw_dump();
        else if(c=='H'||c=='h')say("E=power X=off P=passive A=arm Y=confirm N=cancel R=report D=raw\n");
        else if((c=='E'||c=='e')&&g_report.state==0u){
            if(power_enable())say("[POWER] PE14 HIGH. XL VCC_IO must be ~3.3 V. Check current/temp. Auto-OFF 45s.\n");
            else say("[BLOCKED] Power already tried or PE14 did not read HIGH\n");
        }
        else if(c=='X'||c=='x'){
            release_bus();release_csn(0u);power_off(2u);
            if(g_report.state==1u)g_report.state=0u;
            say("[POWER] PE14 Hi-Z; scans not started\n");
        }
        else if((c=='P'||c=='p')&&g_report.state==0u){passive();passive_print();}
        else if((c=='A'||c=='a')&&g_report.state==0u){
            if(!power_ok())say("[BLOCKED] E first; measure VCC_IO/current before scan\n");
            else{g_report.state=1u;say("ARMED. Y runs ONE X/XL autodetection; N cancels\n");}
        }
        else if((c=='N'||c=='n')&&g_report.state==1u){g_report.state=0u;say("CANCELLED\n");}
        else if((c=='Y'||c=='y')&&g_report.state==1u){
            if(!power_ok()){say("[BLOCKED] PE14 power expired/LOW\n");g_report.state=3u;}
            else autodetect_once();
        }
    }
}
void Default_Handler(void){for(;;){} }
void Reset_Handler(void);
extern uint32_t _estack,_sidata,_sdata,_edata,_sbss,_ebss;
__attribute__((used,section(".isr_vector")))
const uintptr_t vectors[16]={
    [0]=(uintptr_t)&_estack,
    [1]=(uintptr_t)Reset_Handler,
    [2]=(uintptr_t)Default_Handler, [3]=(uintptr_t)Default_Handler,
    [4]=(uintptr_t)Default_Handler, [5]=(uintptr_t)Default_Handler,
    [6]=(uintptr_t)Default_Handler,
    [11]=(uintptr_t)Default_Handler, [12]=(uintptr_t)Default_Handler,
    [14]=(uintptr_t)Default_Handler, [15]=(uintptr_t)Default_Handler
};
void Reset_Handler(void)
{
    uint32_t *to=&_sdata;
    for(uint32_t *from=&_sidata;to<&_edata;) *to++=*from++;
    for(to=&_sbss;to<&_ebss;) *to++=0u;
    init_hw();loop();for(;;){}
}
