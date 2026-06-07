set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "Stacked PC = 0x%08X\n", *(unsigned int*)($msp+0x18)
printf "Stacked LR = 0x%08X\n", *(unsigned int*)($msp+0x14)
printf "Stacked R0..R3, R12 = %08X %08X %08X %08X / %08X\n", *(unsigned int*)$msp, *(unsigned int*)($msp+4), *(unsigned int*)($msp+8), *(unsigned int*)($msp+12), *(unsigned int*)($msp+16)
printf "MSP=0x%08X PSP=0x%08X\n", $msp, $psp

# Verify the trampoline is in flash as expected
printf "\nTrampoline bytes at 0x0801E8A0 (first 8 halfwords):\n"
x/8hx 0x0801E8A0
printf "\nnotify() at 0x0800BBDC:\n"
x/2hx 0x0800BBDC

monitor resume
quit
