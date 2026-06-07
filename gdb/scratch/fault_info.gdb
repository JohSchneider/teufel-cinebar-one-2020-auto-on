set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== HardFault context ===\n"
printf "  PC=0x%08X  xPSR exception_no = %d (3 = HardFault)\n", $pc, *(unsigned int*)($msp+0x1C) & 0x1FF

# Stacked frame on MSP: r0 r1 r2 r3 r12 lr return_pc xpsr (8 words)
printf "  Stacked PC  (faulting instr) = 0x%08X\n", *(unsigned int*)($msp+0x18)
printf "  Stacked LR  (called-from)   = 0x%08X\n", *(unsigned int*)($msp+0x14)
printf "  Stacked R0..R3, R12         = %08X %08X %08X %08X / %08X\n", *(unsigned int*)$msp, *(unsigned int*)($msp+4), *(unsigned int*)($msp+8), *(unsigned int*)($msp+12), *(unsigned int*)($msp+16)
printf "  state[0] = %d  PSP=0x%08X\n", *(unsigned char*)0x200025DC, $psp

monitor resume
quit
