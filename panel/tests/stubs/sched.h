#include <stdint.h>
struct timer {uint32_t waketime; uint_fast8_t (*func)(struct timer *);};
struct task_wake {int wake;};
#define SF_RESCHEDULE 1
#define DECL_INIT(...)
#define DECL_TASK(...)
#define DECL_SHUTDOWN(...)
static void sched_add_timer(struct timer *t) {}
static void sched_wake_task(struct task_wake *w) {w->wake=1;}
static int sched_check_wake(struct task_wake *w) {int r=w->wake; w->wake=0;return r;}
