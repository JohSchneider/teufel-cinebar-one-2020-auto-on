set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
dump binary memory /tmp/firmware/veeprom_live.bin 0x08007000 0x08007800
monitor resume
quit
