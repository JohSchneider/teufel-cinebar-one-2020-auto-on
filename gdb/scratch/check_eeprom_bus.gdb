set pagination off
set confirm off
target extended-remote :3333
monitor halt

printf "\n=== Read the I²C HandleTypeDef at 0x20002734 ===\n"
# First field (offset 0) of I2C_HandleTypeDef is Instance (peripheral base)
printf "Handle.Instance         (offset  0) = 0x%08x\n", *(unsigned int*)0x20002734
printf "Handle.Init.Timing      (offset  4) = 0x%08x\n", *(unsigned int*)0x20002738
printf "Handle.Init.OwnAddr1    (offset  8) = 0x%08x\n", *(unsigned int*)0x2000273c
printf "Handle.Init.Addrmode    (offset 12) = 0x%08x\n", *(unsigned int*)0x20002740
printf "Handle.Init.Dualaddr    (offset 16) = 0x%08x\n", *(unsigned int*)0x20002744

# Read full I²C2 peripheral state (since the test from before enabled I²C2EN)
printf "\n=== I²C2 peripheral (0x40005800) registers ===\n"
printf "  CR1     = 0x%08x  (bit 0 = PE enable)\n", *(unsigned int*)0x40005800
printf "  CR2     = 0x%08x\n",                       *(unsigned int*)0x40005804
printf "  TIMINGR = 0x%08x\n",                       *(unsigned int*)0x40005810
printf "  ISR     = 0x%08x  (bit 4 = NACKF, bit 6 = TC, bit 0 = TXE)\n", *(unsigned int*)0x40005818
printf "\n=== I²C1 peripheral (0x40005400) registers ===\n"
printf "  CR1     = 0x%08x  (bit 0 = PE enable)\n", *(unsigned int*)0x40005400
printf "  CR2     = 0x%08x\n",                       *(unsigned int*)0x40005404
printf "  TIMINGR = 0x%08x\n",                       *(unsigned int*)0x40005410
printf "  ISR     = 0x%08x\n",                       *(unsigned int*)0x40005418

printf "\n=== Also: which other I²C handles exist in RAM? ===\n"
# DSP uses I²C2 — its handle should be somewhere. Let's check the symbol map.
# We don't know for sure but symbols.md said i2c2_mutex_tx uses I²C2 with a handle from somewhere.
# Try a few common candidate addresses
printf "  RAM @ 0x200026d0: %08x %08x\n", *(unsigned int*)0x200026d0, *(unsigned int*)0x200026d4

monitor resume
quit
