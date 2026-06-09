set confirm off
set pagination off
target extended-remote :3333

monitor reset halt

# Confirm we're at Reset_Handler
flushregs
printf "After reset halt: PC = 0x%x\n", $pc

# Single hardware BP at main entry
hbreak *0x080039D4

# Continue using GDB's continue, not monitor resume
continue

# When BP hits, GDB pauses
flushregs
printf "Hit BP at: PC = 0x%x\n", $pc

# Now also set BP at 0x08003AD0 (BL site)
hbreak *0x08003AD0

continue

flushregs
printf "Hit BP at: PC = 0x%x\n", $pc

delete breakpoints
monitor resume
detach
quit
