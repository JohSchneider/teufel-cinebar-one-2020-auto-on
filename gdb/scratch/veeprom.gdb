set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt

printf "\n=== Live flash 0x0801F800 (page candidate 1) ===\n"
x/64xb 0x0801F800

printf "\n=== Live flash 0x0801F000 (page candidate 2) ===\n"
x/64xb 0x0801F000

printf "\n=== Current RAM state for cross-check ===\n"
printf "state[0..7] = %d %d %d %d %d %d %d %d\n", *(unsigned char*)0x200025DC, *(unsigned char*)0x200025DD, *(unsigned char*)0x200025DE, *(unsigned char*)0x200025DF, *(unsigned char*)0x200025E0, *(unsigned char*)0x200025E1, *(unsigned char*)0x200025E2, *(unsigned char*)0x200025E3

monitor resume
quit
