set confirm off
set pagination off
target extended-remote :3333
monitor halt

# FPB registers (Cortex-M0+)
# FP_CTRL  @ 0xE0002000: bit 0 = ENABLE, bit 1 = KEY (write 1 to allow updates)
# FP_REMAP @ 0xE0002004
# FP_COMP0 @ 0xE0002008
# FP_COMP1 @ 0xE000200C
# FP_COMP2 @ 0xE0002010
# FP_COMP3 @ 0xE0002014

printf "FPB state:\n"
printf "  FP_CTRL  (0xE0002000) = 0x%08x  (bit 0 = ENABLE)\n", *(unsigned int*)0xE0002000
printf "  FP_REMAP (0xE0002004) = 0x%08x\n", *(unsigned int*)0xE0002004
printf "  FP_COMP0 (0xE0002008) = 0x%08x  (BP addr / enable bit)\n", *(unsigned int*)0xE0002008
printf "  FP_COMP1 (0xE000200C) = 0x%08x\n", *(unsigned int*)0xE000200C
printf "  FP_COMP2 (0xE0002010) = 0x%08x\n", *(unsigned int*)0xE0002010
printf "  FP_COMP3 (0xE0002014) = 0x%08x\n", *(unsigned int*)0xE0002014

# DEMCR for global enable
# DEMCR @ 0xE000EDFC: bit 24 = TRCENA (DWT/ITM enable, not FPB)
# Actually FPB doesn't need DEMCR

# DHCSR — debug halting control
printf "\n  DHCSR (0xE000EDF0) = 0x%08x  (bit 1 = HALT, bit 0 = DEBUGEN)\n", *(unsigned int*)0xE000EDF0

# Set a BP, then re-read FPB
hbreak *0x0800d66c
printf "\nAfter hbreak *0x0800d66c:\n"
printf "  FP_CTRL  = 0x%08x  (should be 3 if BP works)\n", *(unsigned int*)0xE0002000
printf "  FP_COMP0 = 0x%08x  (should contain 0x0800d66c with enable)\n", *(unsigned int*)0xE0002008

delete breakpoints
monitor resume
detach
quit
