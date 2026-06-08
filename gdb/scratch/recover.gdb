set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
delete breakpoints
monitor reset halt
monitor reset run
quit
