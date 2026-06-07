set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "Bar alive at PC = 0x%08X, MSP=0x%08X (or PSP if Thread mode)\n", $pc, $sp
printf "\n=== RAM probe — looking for stable/empty regions (4×8 words each) ===\n"

printf "\n--- 0x20002700 ---\n"
x/8wx 0x20002700
printf "--- 0x20002800 ---\n"
x/8wx 0x20002800
printf "--- 0x20002A00 ---\n"
x/8wx 0x20002A00
printf "--- 0x20002C00 ---\n"
x/8wx 0x20002C00
printf "--- 0x20002E00 ---\n"
x/8wx 0x20002E00
printf "--- 0x20003000 ---\n"
x/8wx 0x20003000
printf "--- 0x20003200 ---\n"
x/8wx 0x20003200
printf "--- 0x20003400 ---\n"
x/8wx 0x20003400
printf "--- 0x20003600 ---\n"
x/8wx 0x20003600
printf "--- 0x20003800 ---\n"
x/8wx 0x20003800
printf "--- 0x20003A00 ---\n"
x/8wx 0x20003A00
printf "--- 0x20003C00 (current fw_24 buf — clearly used) ---\n"
x/8wx 0x20003C00
printf "--- 0x20003E00 ---\n"
x/8wx 0x20003E00
printf "--- 0x20003F80 (top 128 bytes) ---\n"
x/8wx 0x20003F80

monitor resume
quit
