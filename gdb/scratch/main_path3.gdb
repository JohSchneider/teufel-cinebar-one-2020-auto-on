set confirm off
set pagination off
target extended-remote :3333

monitor reset halt
flushregs
printf "After reset_halt: PC=0x%x\n", $pc

# What does __main jump to? Read the literal at 0x080000CC
printf "Literal at 0x080000CC = 0x%08x\n", *(unsigned int*)0x080000CC

# Single BP at 0x080039D4
hbreak *0x080039D4

monitor resume
shell sleep 2
monitor halt

flushregs
printf "After 2s: PC=0x%x (should be 0x80039d4 if BP fired)\n", $pc

# Check breakpoint hit count
info breakpoints

delete breakpoints
monitor resume
detach
quit
