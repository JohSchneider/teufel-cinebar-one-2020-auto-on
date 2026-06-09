set pagination off
set confirm off
target extended-remote :3333

monitor halt

# Correct state struct base for the PA0 service thread: 0x200025F0 (from literal at 0x800eaf4)
# r5 in the thread = base + 0x20 = 0x20002610

printf "\n=== BASELINE thread state @ 0x20002610 ===\n"
printf "  +0..7:        %02x %02x %02x %02x  %02x %02x %02x %02x\n", *(unsigned char*)0x20002610, *(unsigned char*)0x20002611, *(unsigned char*)0x20002612, *(unsigned char*)0x20002613, *(unsigned char*)0x20002614, *(unsigned char*)0x20002615, *(unsigned char*)0x20002616, *(unsigned char*)0x20002617
printf "  +8 (active): 0x%02x   +9 (initial): 0x%02x\n", *(unsigned char*)0x20002618, *(unsigned char*)0x20002619
printf "  +10..+15:    %02x %02x %02x %02x %02x %02x\n", *(unsigned char*)0x2000261a, *(unsigned char*)0x2000261b, *(unsigned char*)0x2000261c, *(unsigned char*)0x2000261d, *(unsigned char*)0x2000261e, *(unsigned char*)0x2000261f

# Now use a SHORT direct test: don't override, just COUNT hits
# Approach: BP fires, prints r0 + caller LR, then continues. We see if it gets hit at all.
printf "\n=== Set HBP with reporting (no override yet) ===\n"
hbreak *0x0800F148
commands
  silent
  printf "BP hit: r0=%d  lr=0x%08x\n", $r0, $lr
  continue
end

monitor resume
shell sleep 2
monitor halt

printf "\n(Above lines show HBP hits during 2s — empty means BP never fired)\n"

delete breakpoints

# Now ACTIVELY override and run again
printf "\n=== Set HBP with r0=0 override ===\n"
hbreak *0x0800F148
commands
  silent
  printf "BP-override: was r0=%d, lr=0x%08x — set r0=0\n", $r0, $lr
  set $r0 = 0
  continue
end

monitor resume
shell sleep 3
monitor halt

printf "\n=== AFTER override, thread state @ 0x20002610 ===\n"
printf "  +0..7:        %02x %02x %02x %02x  %02x %02x %02x %02x\n", *(unsigned char*)0x20002610, *(unsigned char*)0x20002611, *(unsigned char*)0x20002612, *(unsigned char*)0x20002613, *(unsigned char*)0x20002614, *(unsigned char*)0x20002615, *(unsigned char*)0x20002616, *(unsigned char*)0x20002617
printf "  +8 (active): 0x%02x   +9 (initial): 0x%02x\n", *(unsigned char*)0x20002618, *(unsigned char*)0x20002619
printf "  +10..+15:    %02x %02x %02x %02x %02x %02x\n", *(unsigned char*)0x2000261a, *(unsigned char*)0x2000261b, *(unsigned char*)0x2000261c, *(unsigned char*)0x2000261d, *(unsigned char*)0x2000261e, *(unsigned char*)0x2000261f

printf "GPIOA ODR after: 0x%08x\n", *(unsigned int*)0x48000014
printf "RCC_APB1ENR after: 0x%08x  (was 0x10000012; bit23=USB, bit22=I2C2)\n", *(unsigned int*)0x4002101c

delete breakpoints
monitor resume
quit
