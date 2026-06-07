set confirm off
set pagination off
set remotetimeout 120
target extended-remote :3333
monitor halt
delete breakpoints

# BP at 0x0800BCDC (right after osMessageQueueGet returns; msg ptr in r1)
break *0x0800BCDC
commands
silent
printf "★ DISPATCH: cmd_id=%d  value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

printf "\nBP armed at 0x0800BCDC. Bar resuming.\n"
printf "Press an IR button now (e.g., volume up, then mute, then mode).\n"
printf "Each press will print one line. Listening for 30 seconds...\n\n"

monitor resume
shell sleep 30
monitor halt
printf "\nDone listening. Detaching.\n"
delete breakpoints
monitor resume
quit
