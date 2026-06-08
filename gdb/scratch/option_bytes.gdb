set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "\nOption bytes at 0x1FFFF800:\n"
x/8wx 0x1FFFF800
printf "\nFLASH_OBR (option byte register, 0x4002201C):\n"
x/wx 0x4002201C
printf "\nUSB BCDR (battery charging detection) 0x40005C50:\n"
x/wx 0x40005C50
printf "\nUSB clock enabled? RCC_APB1ENR (0x4002101C) bit 23:\n"
x/wx 0x4002101C
monitor resume
quit
