set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor reset halt
monitor flash write_image erase /tmp/firmware/firmware_24_nop-transition-state.bin 0x08000000
monitor verify_image /tmp/firmware/firmware_24_nop-transition-state.bin 0x08000000
monitor reset run
quit
