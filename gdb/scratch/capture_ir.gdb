set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints
break *0x0800AB00
commands
silent
printf "[IR] post_event_type0  r0=0x%08X (%d)  lr=0x%08X\n", $r0, $r0, $lr
continue
end
continue
