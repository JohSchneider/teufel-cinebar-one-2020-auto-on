set confirm off
set pagination off
set remotetimeout 20
target extended-remote :3333
monitor halt
printf "\n=== 0x0801F800 (first 32 bytes) ===\n"
x/8wx 0x0801F800
printf "\n=== 0x0801F000 ===\n"
x/8wx 0x0801F000
monitor resume
quit
