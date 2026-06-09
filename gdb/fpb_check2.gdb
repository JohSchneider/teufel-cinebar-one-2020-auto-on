set confirm off
set pagination off
target extended-remote :3333
monitor halt

hbreak *0x0800d66c

# Resume the bar — this should make OpenOCD actually write FP_COMP0
monitor resume

# Then halt to read register state
shell sleep 0.1
monitor halt

flushregs
printf "FP_CTRL  = 0x%08x\n", *(unsigned int*)0xE0002000
printf "FP_COMP0 = 0x%08x  (expected to contain 0x0800d66c with enable bit)\n", *(unsigned int*)0xE0002008
printf "FP_COMP1 = 0x%08x\n", *(unsigned int*)0xE000200C
printf "PC after halt = 0x%x  (if BP worked, should be 0x0800d66c)\n", $pc

delete breakpoints
monitor resume
detach
quit
