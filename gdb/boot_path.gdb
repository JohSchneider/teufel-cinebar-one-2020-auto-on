set confirm off
set pagination off
target extended-remote :3333

monitor reset halt
flushregs

# Decode the actual reset chain
printf "=== Boot chain decode ===\n"
printf "Reset_Handler at 0x080000D4: jumps to SystemInit at 0x%08x\n", *(unsigned int*)0x080000E8
printf "Then jumps to __main at      0x%08x\n", *(unsigned int*)0x080000EC
printf "__main bx_r0 target lives at 0x%08x  <-- this is the value bx jumps to\n", *(unsigned int*)0x080000CC
printf "\nAfter reset_halt: PC=0x%x\n", $pc

# BP at Reset_Handler (should fire immediately on resume)
hbreak *0x080000D4

# BPs at the various jump points
hbreak *0x08002EA0
hbreak *0x080000C0
hbreak *0x080039D4

monitor resume
shell sleep 1
monitor halt
flushregs
printf "\nAfter 1s resume: PC = 0x%x\n", $pc
info breakpoints

delete breakpoints
monitor resume
detach
quit
