set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "\n=== PA15 current state ===\n"
printf "  GPIOA MODER (0x48000000) = 0x%08X  (PA15 mode bits 30..31)\n", *(unsigned int*)0x48000000
printf "  PA15 mode = %d (0=input, 1=output, 2=AF, 3=analog)\n", (*(unsigned int*)0x48000000 >> 30) & 0x3
printf "  GPIOA PUPDR (0x4800000C) = 0x%08X  (PA15 pull bits 30..31)\n", *(unsigned int*)0x4800000C
printf "  PA15 pull = %d (0=none, 1=pull-up, 2=pull-down)\n", (*(unsigned int*)0x4800000C >> 30) & 0x3
printf "  GPIOA IDR  (0x48000010) bit 15 = %d  ← THE strap value (external)\n", (*(unsigned int*)0x48000010 >> 15) & 1
printf "  GPIOA ODR  (0x48000014) bit 15 = %d  ← what STM32 drives (irrelevant if input)\n", (*(unsigned int*)0x48000014 >> 15) & 1
monitor resume
quit
