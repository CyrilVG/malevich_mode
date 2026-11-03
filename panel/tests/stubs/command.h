#include <assert.h>
#include <stdint.h>
#define DECL_CONSTANT_STR(...)
#define DECL_CONSTANT(...)
#define DECL_COMMAND(...)
#define DECL_COMMAND_FLAGS(...)
#define HF_IN_SHUTDOWN 1
#define shutdown(s) assert(!s)
#define sendf(...) ((void)0)
static void *command_decode_ptr(uint32_t p) {return (void *)(uintptr_t)p;}
