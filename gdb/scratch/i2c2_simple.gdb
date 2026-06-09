set pagination off
set confirm off
target extended-remote :3333
monitor halt

printf "\n=== I²C2 state ===\n"
printf "  CR1=0x%08x  TIMINGR=0x%08x  ISR=0x%08x\n", *(unsigned int*)0x40005800, *(unsigned int*)0x40005810, *(unsigned int*)0x40005818

# Make sure timing is set (use I²C1's value as known-good)
if *(unsigned int*)0x40005810 == 0
  set *(unsigned int*)0x40005800 = 0
  set *(unsigned int*)0x40005810 = 0x0000020b
  set *(unsigned int*)0x40005800 = 1
  printf "  set TIMINGR=0x0000020b\n"
end

# Clear flags
set *(unsigned int*)0x4000581c = 0xff
shell sleep 0.05
printf "\nAfter ICR write: ISR=0x%08x\n", *(unsigned int*)0x40005818

# Probe 0x50 (= 8-bit 0xA0)
printf "\n=== Probe 0x50: write CR2=START + AUTOEND + SADD=0xA0 + 0 bytes ===\n"
set *(unsigned int*)0x40005804 = (0x50 << 1) | (1 << 13) | (1 << 25)
shell sleep 0.05
printf "ISR after probe = 0x%08x\n", *(unsigned int*)0x40005818
printf "  NACKF=%d STOPF=%d BERR=%d ARLO=%d BUSY=%d\n", (*(unsigned int*)0x40005818>>4)&1, (*(unsigned int*)0x40005818>>5)&1, (*(unsigned int*)0x40005818>>8)&1, (*(unsigned int*)0x40005818>>9)&1, (*(unsigned int*)0x40005818>>15)&1

# Probe 0x44 (= 8-bit 0x88, the DSP-blob-upload address per symbols.md, just as a sanity check — should NACK on I²C2 because DSP is on I²C1)
printf "\n=== Sanity-check probe 0x44 (DSP-upload addr — should fail on I²C2) ===\n"
set *(unsigned int*)0x4000581c = 0xff
set *(unsigned int*)0x40005804 = (0x44 << 1) | (1 << 13) | (1 << 25)
shell sleep 0.05
printf "ISR after probe = 0x%08x  NACKF=%d STOPF=%d\n", *(unsigned int*)0x40005818, (*(unsigned int*)0x40005818>>4)&1, (*(unsigned int*)0x40005818>>5)&1

# Probe 0x59 (= 8-bit 0xB2, DSP runtime — also wrong bus)
printf "\n=== Sanity-check probe 0x59 (DSP runtime addr — also wrong bus) ===\n"
set *(unsigned int*)0x4000581c = 0xff
set *(unsigned int*)0x40005804 = (0x59 << 1) | (1 << 13) | (1 << 25)
shell sleep 0.05
printf "ISR after probe = 0x%08x  NACKF=%d STOPF=%d\n", *(unsigned int*)0x40005818, (*(unsigned int*)0x40005818>>4)&1, (*(unsigned int*)0x40005818>>5)&1

# Cleanup
set *(unsigned int*)0x4000581c = 0xff

printf "\n=== Done; resume ===\n"
monitor resume
quit
