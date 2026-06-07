set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints
monitor reset halt
delete breakpoints
monitor reset run
quit
