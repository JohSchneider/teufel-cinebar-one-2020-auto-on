set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "PC=0x%08X  state=%d\n", $pc, *(unsigned char*)0x200025DC
printf "ring magic = 0x%08X (need 0xC1BAFEED if notify ever ran)\n", *(unsigned int*)0x20003E00
printf "ring count = %d\n", *(unsigned int*)0x20003E08

printf "\n--- Faulting frame on MSP ---\n"
printf "  Stacked PC (= faulting instr) = 0x%08X\n", *(unsigned int*)($msp+0x18)
printf "  Stacked LR                    = 0x%08X\n", *(unsigned int*)($msp+0x14)
printf "  R0..R3 = %08X %08X %08X %08X\n", *(unsigned int*)$msp, *(unsigned int*)($msp+4), *(unsigned int*)($msp+8), *(unsigned int*)($msp+12)

printf "\n--- Inspect notify entry + first trampoline bytes ---\n"
x/2hx 0x0800BBDC
x/8hx 0x0801E8A0

monitor resume
quit
