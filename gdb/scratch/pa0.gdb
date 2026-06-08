set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "\nGPIOA IDR (0x48000010) = 0x%08X  → PA0 bit = %d  PA1=%d  PA2=%d  PA3=%d  PA4=%d  PA5=%d\n", \
  *(unsigned int*)0x48000010, \
  (*(unsigned int*)0x48000010) & 1, \
  ((*(unsigned int*)0x48000010) >> 1) & 1, \
  ((*(unsigned int*)0x48000010) >> 2) & 1, \
  ((*(unsigned int*)0x48000010) >> 3) & 1, \
  ((*(unsigned int*)0x48000010) >> 4) & 1, \
  ((*(unsigned int*)0x48000010) >> 5) & 1
printf "\nGPIOA MODER (0x48000000) = 0x%08X\n", *(unsigned int*)0x48000000
printf "  PA0 mode  = %d (0=input, 1=output, 2=AF, 3=analog)\n", (*(unsigned int*)0x48000000) & 0x3
printf "  PA5 mode  = %d\n", ((*(unsigned int*)0x48000000) >> 10) & 0x3
monitor resume
quit
