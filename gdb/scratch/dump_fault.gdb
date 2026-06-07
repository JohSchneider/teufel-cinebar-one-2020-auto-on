set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
printf "Current state:\n"
printf "  PC = 0x%08X (should be HardFault handler if stuck)\n", $pc
printf "  MSP = 0x%08X\n", $sp
printf "  xPSR = 0x%08X  (low byte = exception number; 3 = HardFault)\n", $xpsr
printf "\n"
printf "Exception frame at MSP (8 words: r0, r1, r2, r3, r12, LR, PC@fault, xPSR):\n"
x/8wx $sp
printf "\n=== Tip: the 7th word = PC at fault — tells us where the crash happened ===\n"
quit
