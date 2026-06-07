set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "state[+0] (power)  = %d (1=stby, 2=active)\n", *(unsigned char*)0x200025DC
printf "state[+1] (volume) = %d\n", *(unsigned char*)0x200025DD
printf "state[+2]          = %d\n", *(unsigned char*)0x200025DE
printf "state[+3] (source) = %d\n", *(unsigned char*)0x200025DF
printf "state[+4]          = %d\n", *(unsigned char*)0x200025E0
monitor resume
quit
