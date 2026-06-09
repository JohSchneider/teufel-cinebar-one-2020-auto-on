set confirm off
set pagination off
target extended-remote :3333
monitor reset halt
flushregs
printf "PC after reset_halt = 0x%x\n", $pc

hbreak *0x080000D4
info breakpoints

# Use GDB continue with timeout fallback
continue
