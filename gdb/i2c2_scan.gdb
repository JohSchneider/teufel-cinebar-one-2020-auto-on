set pagination off
set confirm off
target extended-remote :3333
monitor halt

printf "\n=== I²C2 pre-state ===\n"
printf "  CR1=0x%08x  CR2=0x%08x  TIMINGR=0x%08x  ISR=0x%08x\n", *(unsigned int*)0x40005800, *(unsigned int*)0x40005804, *(unsigned int*)0x40005810, *(unsigned int*)0x40005818

# Save state
set $cr2_save = *(unsigned int*)0x40005804

# Clear any sticky NACKF / STOPF first by writing to ICR (offset 0x1C)
# ICR: NACKCF=bit4, STOPCF=bit5
set *(unsigned int*)0x4000581c = 0x30

printf "\n=== Scan: try each 7-bit address 0x40..0x60 — look for ACK ===\n"
set $addr = 0x40
while $addr <= 0x60
  # Build CR2 for 0-byte write to (addr<<1):
  # SADD bits 7:1 = addr, RD_WRN=0, NBYTES=0, AUTOEND=1, START=1
  set $sadd = $addr << 1
  set *(unsigned int*)0x40005804 = $sadd | (1 << 13) | (1 << 25)
  
  # Wait for STOPF (bit 5) or NACKF (bit 4)
  set $timeout = 1000
  while (*(unsigned int*)0x40005818 & 0x30) == 0
    set $timeout = $timeout - 1
    if $timeout == 0
      loop_break
    end
  end
  
  set $isr = *(unsigned int*)0x40005818
  if ($isr & 0x10) != 0
    # NACKF set — no device at this address
  else
    if ($isr & 0x20) != 0
      printf "  ACK at 7-bit addr 0x%02x (8-bit 0x%02x)  ISR=0x%08x\n", $addr, $sadd, $isr
    end
  end
  
  # Clear NACKF and STOPF for next iteration
  set *(unsigned int*)0x4000581c = 0x30
  
  set $addr = $addr + 1
end

printf "\nScan complete.\n"

# Specifically retry 0x50 (the suspected EEPROM address) with detailed reporting
printf "\n=== Detailed probe at 0x50 (= 8-bit 0xA0) ===\n"
set *(unsigned int*)0x40005804 = (0x50 << 1) | (1 << 13) | (1 << 25)
set $timeout = 10000
while (*(unsigned int*)0x40005818 & 0x30) == 0
  set $timeout = $timeout - 1
  if $timeout == 0
    loop_break
  end
end
printf "  ISR after probe = 0x%08x\n", *(unsigned int*)0x40005818
printf "  NACKF (bit 4) = %d  (1 = no device)\n", (*(unsigned int*)0x40005818 >> 4) & 1
printf "  STOPF (bit 5) = %d  (1 = transaction completed)\n", (*(unsigned int*)0x40005818 >> 5) & 1
printf "  BERR  (bit 8) = %d  (1 = bus error)\n", (*(unsigned int*)0x40005818 >> 8) & 1
printf "  Timeout counter = %d (=0 means we ran out)\n", $timeout

# Cleanup: clear flags
set *(unsigned int*)0x4000581c = 0x30
# Restore CR2
set *(unsigned int*)0x40005804 = $cr2_save

printf "\n=== Done; resuming bar ===\n"
monitor resume
quit
