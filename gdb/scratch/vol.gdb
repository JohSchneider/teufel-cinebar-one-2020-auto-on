set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "state[+1] (volume) = %d (0x%02X)\n", *(unsigned char*)0x200025DD, *(unsigned char*)0x200025DD
printf "state[+0..+7]    = %d %d %d %d %d %d %d %d\n", *(unsigned char*)0x200025DC, *(unsigned char*)0x200025DD, *(unsigned char*)0x200025DE, *(unsigned char*)0x200025DF, *(unsigned char*)0x200025E0, *(unsigned char*)0x200025E1, *(unsigned char*)0x200025E2, *(unsigned char*)0x200025E3
monitor resume
quit
