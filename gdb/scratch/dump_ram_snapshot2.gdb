set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
printf "PC=0x%08X  PSP=0x%08X\n", $pc, $sp
dump memory /tmp/firmware/gdb/scratch/ram_snap2.bin 0x20000000 0x20004000
printf "Snapshot 2 saved (16 KB).\n"
monitor resume
quit
