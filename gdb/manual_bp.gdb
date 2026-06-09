set confirm off
set pagination off
target extended-remote :3333
monitor halt

# Cortex-M0+ FPB FP_COMPx encoding:
# bit 0:    ENABLE
# bits 28:2: COMP_ADDR (address bits 28:2)
# bits 30:29: REPLACE (01=lower halfword, 10=upper, 11=word)
# For 0x0800d66c (bit 1 = 0 = lower halfword): REPLACE=01
# FP_COMP = (1<<30) | (0x0800d66c & 0x1FFFFFFC) | 1 = 0x4800d66d

# Verify FPB is enabled
printf "Before: FP_CTRL = 0x%08x\n", *(unsigned int*)0xE0002000
printf "Before: FP_COMP0 = 0x%08x\n", *(unsigned int*)0xE0002008

# Enable FPB (FP_CTRL.KEY = bit 1 must be set when writing, ENABLE = bit 0)
set *(unsigned int*)0xE0002000 = 3

# Manually write FP_COMP0 for BP at 0x0800d66c (osKernelGetTickCount)
# Lower halfword breakpoint: REPLACE=01, addr=0x0800d66c & 0x1FFFFFFC, ENABLE=1
set *(unsigned int*)0xE0002008 = 0x4800d66d

printf "After:  FP_CTRL  = 0x%08x\n", *(unsigned int*)0xE0002000
printf "After:  FP_COMP0 = 0x%08x\n", *(unsigned int*)0xE0002008

# Resume and see if it halts at 0x0800d66c
monitor resume
shell sleep 1
monitor halt

flushregs
printf "After 1s: PC = 0x%x  (if manual BP worked: should be 0x0800d66c)\n", $pc

# Clear manual BP
set *(unsigned int*)0xE0002008 = 0

monitor resume
detach
quit
