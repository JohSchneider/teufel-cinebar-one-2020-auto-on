set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "\n=== Before: PA15 idle ===\n"
printf "  PA15 strap value (IDR bit 15) = %d\n", (*(unsigned int*)0x48000010 >> 15) & 1

# Step 1: ensure ODR bit 15 = 0 (so when we flip to output it drives LOW)
set *(unsigned int*)0x48000018 = (1 << 31)
# Step 2: set OTYPER bit 15 = 1 (open-drain)
set *(unsigned int*)0x48000004 |= (1 << 15)
# Step 3: set MODER bits 30-31 = 0b01 (output)
set *(unsigned int*)0x48000000 = (*(unsigned int*)0x48000000 & ~(0x3 << 30)) | (0x1 << 30)

printf "\n=== After: PA15 driven LOW (open-drain) ===\n"
printf "  GPIOA MODER bits 30..31 = %d (1=output)\n", (*(unsigned int*)0x48000000 >> 30) & 0x3
printf "  GPIOA OTYPER bit 15     = %d (1=open-drain)\n", (*(unsigned int*)0x48000004 >> 15) & 1
printf "  GPIOA IDR bit 15        = %d (should be 0 now)\n", (*(unsigned int*)0x48000010 >> 15) & 1
printf "\nNow run 'lsusb' on the PC.\n"
printf "Then re-run with /tmp/firmware/gdb/scratch/pa15_restore.gdb to put PA15 back.\n"

monitor resume
quit
