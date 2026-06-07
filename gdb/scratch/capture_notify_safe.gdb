set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor reset halt
monitor reset run
# Wait for bar to boot + stabilize
shell sleep 8
monitor halt
delete breakpoints
break *0x0800BBDC
commands
silent
printf "[NOTIFY] ch=%d val=0x%08X  lr=0x%08X  r2=0x%08X r3=0x%08X\n", $r0, $r1, $lr, $r2, $r3
continue
end
printf "\n=== bp at notify armed; press IR-power now ===\n\n"
continue
