set confirm off
set pagination off
set remotetimeout 90
target extended-remote :3333
monitor halt
delete breakpoints

break *0x0800AB00
commands
silent
printf "[post_event_type0] r0=%d  LR=0x%08X  → BL was at 0x%08X\n", $r0, $lr, ($lr - 5) & ~1
continue
end

printf "\nBP at post_event_type0 (0x0800AB00).\n"
printf "Fire your Arduino IR-power code now. 45 seconds.\n\n"
monitor resume
shell sleep 45
monitor halt
printf "\nDone.\n"
delete breakpoints
monitor resume
quit
