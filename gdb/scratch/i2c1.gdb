set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "\nI2C1 CR1 (0x40005400) = 0x%08X\n", *(unsigned int*)0x40005400
printf "I2C1 ISR (0x40005418) = 0x%08X\n", *(unsigned int*)0x40005418
printf "I2C2 CR1 (0x40005800) = 0x%08X  (DSP bus)\n", *(unsigned int*)0x40005800

printf "\nI2C1-struct RAM area at 0x200024C8 (32 bytes):\n"
x/8wx 0x200024C8

printf "\nRAM at 0x20002620 (the other I2C1 ref):\n"
x/8wx 0x20002620

monitor resume
quit
