set pagination off
set confirm off
target extended-remote :3333

monitor halt

printf "\n=== Halt point right now ===\n"
printf "PC = 0x%08x   LR = 0x%08x   SP = 0x%08x\n", $pc, $lr, $sp
printf "PSP = 0x%08x   CONTROL = 0x%08x\n", $psp, $control

# Read the LIVE service thread state at base + 0x20 (= r5 in the thread)
# Base is 0x2000243C per the function pointer table. r5 = base + 0x20 = 0x2000245C
printf "\nThread state struct +0x20 (offsets seen in disasm):\n"
printf "  +0 .. +15:   %02x %02x %02x %02x  %02x %02x %02x %02x\n", *(unsigned char*)0x2000245c, *(unsigned char*)0x2000245d, *(unsigned char*)0x2000245e, *(unsigned char*)0x2000245f, *(unsigned char*)0x20002460, *(unsigned char*)0x20002461, *(unsigned char*)0x20002462, *(unsigned char*)0x20002463
printf "  +8 (active): 0x%02x   +9 (initial): 0x%02x\n", *(unsigned char*)0x20002464, *(unsigned char*)0x20002465
printf "  +10..+15:    %02x %02x %02x %02x %02x %02x\n", *(unsigned char*)0x20002466, *(unsigned char*)0x20002467, *(unsigned char*)0x20002468, *(unsigned char*)0x20002469, *(unsigned char*)0x2000246a, *(unsigned char*)0x2000246b

# Counter approach: set BP at 0x0800F148 with hit-count check
printf "\n=== Set HBP and check hit count over 3s ===\n"
hbreak *0x0800F148
commands
  silent
  set $r0 = 0
  continue
end

monitor resume
shell sleep 3
monitor halt

# Tell GDB to report hit count
info breakpoints
delete breakpoints

# Snapshot again after the 3 seconds
printf "\nThread state +0x20 AFTER 3s:\n"
printf "  +0 .. +15:   %02x %02x %02x %02x  %02x %02x %02x %02x\n", *(unsigned char*)0x2000245c, *(unsigned char*)0x2000245d, *(unsigned char*)0x2000245e, *(unsigned char*)0x2000245f, *(unsigned char*)0x20002460, *(unsigned char*)0x20002461, *(unsigned char*)0x20002462, *(unsigned char*)0x20002463
printf "  +8 (active): 0x%02x   +9 (initial): 0x%02x\n", *(unsigned char*)0x20002464, *(unsigned char*)0x20002465
printf "  +10..+15:    %02x %02x %02x %02x %02x %02x\n", *(unsigned char*)0x20002466, *(unsigned char*)0x20002467, *(unsigned char*)0x20002468, *(unsigned char*)0x20002469, *(unsigned char*)0x2000246a, *(unsigned char*)0x2000246b

printf "PC at halt: 0x%08x\n", $pc

monitor resume
quit
