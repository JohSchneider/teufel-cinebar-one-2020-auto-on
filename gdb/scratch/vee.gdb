set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
dump binary memory /tmp/firmware/veeprom_after_fw22.bin 0x08007000 0x08007400
monitor resume
quit
