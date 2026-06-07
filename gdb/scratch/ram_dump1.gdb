set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
dump binary memory /tmp/firmware/ram_snap_A.bin 0x20000000 0x20004000
monitor resume
quit
