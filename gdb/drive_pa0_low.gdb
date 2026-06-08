set pagination off
set confirm off
target extended-remote :3333

monitor halt

printf "\n=== BASELINE ===\n"
printf "GPIOA MODER = 0x%08x  ODR = 0x%08x  IDR = 0x%08x\n", *(unsigned int*)0x48000000, *(unsigned int*)0x48000014, *(unsigned int*)0x48000010
printf "GPIOC ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000814, *(unsigned int*)0x48000810
printf "RCC_APB1ENR = 0x%08x  (bit23=USB, bit22=I2C2)\n", *(unsigned int*)0x4002101c

# Save originals
set $orig_moder = *(unsigned int*)0x48000000
set $orig_odr   = *(unsigned int*)0x48000014

printf "\n=== Drive PA0 LOW via GDB (configure as output PP, ODR.0 = 0) ===\n"
# 1. ODR.0 = 0 first (so when we switch to output, it goes LOW immediately)
set *(unsigned int*)0x48000014 = $orig_odr & ~0x1
# 2. MODER bits 0-1: clear, then set to 01 (general purpose output)
set *(unsigned int*)0x48000000 = ($orig_moder & ~0x3) | 0x1

printf "After PA0->OUT-LOW: MODER=0x%08x  ODR=0x%08x  IDR=0x%08x\n", *(unsigned int*)0x48000000, *(unsigned int*)0x48000014, *(unsigned int*)0x48000010

monitor resume
printf "\n=== Run 5s with PA0 forced LOW ===\n"
shell sleep 5

monitor halt
printf "\n=== AFTER 5s ===\n"
printf "GPIOA MODER = 0x%08x  ODR = 0x%08x  IDR = 0x%08x\n", *(unsigned int*)0x48000000, *(unsigned int*)0x48000014, *(unsigned int*)0x48000010
printf "GPIOB MODER = 0x%08x  ODR = 0x%08x\n", *(unsigned int*)0x48000400, *(unsigned int*)0x48000414
printf "GPIOC MODER = 0x%08x  ODR = 0x%08x  IDR = 0x%08x\n", *(unsigned int*)0x48000800, *(unsigned int*)0x48000814, *(unsigned int*)0x48000810
printf "GPIOF ODR = 0x%08x\n", *(unsigned int*)0x48001414
printf "RCC_APB1ENR = 0x%08x  RCC_AHBENR = 0x%08x\n", *(unsigned int*)0x4002101c, *(unsigned int*)0x40021014
printf "Thread state[+8] @ 0x20002618 = 0x%02x  state[+9] = 0x%02x\n", *(unsigned char*)0x20002618, *(unsigned char*)0x20002619
printf "PC at this halt = 0x%08x\n", $pc

printf "\n=== Restore PA0 to original config ===\n"
set *(unsigned int*)0x48000000 = $orig_moder
set *(unsigned int*)0x48000014 = $orig_odr
printf "Restored: MODER=0x%08x  ODR=0x%08x\n", *(unsigned int*)0x48000000, *(unsigned int*)0x48000014

monitor resume
quit
