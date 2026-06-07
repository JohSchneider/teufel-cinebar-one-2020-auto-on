set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "=== Step 1: reflash fw_23 to recover ===\n"
monitor flash write_image erase /tmp/firmware/firmware_23_music-mode-default.bin 0x08000000
monitor reset halt
monitor reset run

# Wait a few seconds for bar to boot + stabilize
shell sleep 8
monitor halt

printf "=== Step 2: probe RAM at multiple candidate offsets ===\n"
printf "Bar is alive at PC = 0x%08X\n", $pc
printf "Looking for regions that show stable / 0xFF / 0x00 patterns (likely unused):\n"

printf "\n--- 0x20002700 (right after known globals) ---\n"
x/8wx 0x20002700
printf "\n--- 0x20002800 ---\n"
x/8wx 0x20002800
printf "\n--- 0x20003000 ---\n"
x/8wx 0x20003000
printf "\n--- 0x20003400 ---\n"
x/8wx 0x20003400
printf "\n--- 0x20003800 ---\n"
x/8wx 0x20003800
printf "\n--- 0x20003C00 (where fw_24 placed its buf — clearly NOT safe) ---\n"
x/8wx 0x20003C00
printf "\n--- 0x20003F00 (very top of RAM) ---\n"
x/8wx 0x20003F00

monitor resume
quit
