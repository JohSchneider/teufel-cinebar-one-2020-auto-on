set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "\n=== Bar state ===\n"
printf "  state[0] = %d  (1=stby, 2=active)\n", *(unsigned char*)0x200025DC

printf "\n=== Active-rail / DSP-control pins ===\n"
set $odra = *(unsigned int*)0x48000014
set $odrb = *(unsigned int*)0x48000414
set $odrc = *(unsigned int*)0x48000814
set $odrf = *(unsigned int*)0x48001414
printf "  GPIOA ODR = 0x%08X   PA2 = %d  (Toslink rail master)\n", $odra, ($odra >> 2) & 1
printf "  GPIOB ODR = 0x%08X   PB7 = %d  (Aux — DSP power suspect)\n", $odrb, ($odrb >> 7) & 1
printf "  GPIOC ODR = 0x%08X   PC15= %d  (Aux)\n", $odrc, ($odrc >> 15) & 1
printf "  GPIOF ODR = 0x%08X   PF0 = %d  (DSP reset; LOW=in reset)\n", $odrf, ($odrf) & 1

printf "\n=== I2C2 (DSP control bus) state ===\n"
printf "  I2C2 CR1 = 0x%08X (bit 0 = PE; 1 = enabled)\n", *(unsigned int*)0x40005800

monitor resume
quit
