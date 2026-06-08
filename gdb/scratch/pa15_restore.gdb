set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

# Set MODER bits 30-31 back to 0b00 (input)
set *(unsigned int*)0x48000000 = (*(unsigned int*)0x48000000 & ~(0x3 << 30))
# Set OTYPER bit 15 back to 0 (push-pull, doesn't matter while input)
set *(unsigned int*)0x48000004 = (*(unsigned int*)0x48000004 & ~(1 << 15))

printf "\n=== PA15 restored to input ===\n"
printf "  PA15 strap value (IDR bit 15) = %d (should be 1 again)\n", (*(unsigned int*)0x48000010 >> 15) & 1
monitor resume
quit
