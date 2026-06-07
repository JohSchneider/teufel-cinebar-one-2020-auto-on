set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Bar at 0x0800A740 (transition_state entry) ===\n"
x/4hx 0x0800A740
printf "\n=== Bar at 0x0801E880 (Shim 3 if fw_23) ===\n"
x/8hx 0x0801E880
printf "\n=== Bar at 0x0800AD12 (call site) ===\n"
x/2hx 0x0800AD12
printf "\nState[0] = %d, PC = 0x%08X\n", *(unsigned char*)0x200025DC, $pc
monitor resume
quit
