set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "PC=0x%08X\n", $pc
monitor resume
quit
