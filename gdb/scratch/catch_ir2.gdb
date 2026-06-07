set confirm off
set pagination off
set remotetimeout 120
target extended-remote :3333
monitor halt
delete breakpoints

# Two BPs: one after queue-get (catches all dispatched msgs)
# and one at the IR handler itself (catches if path is hit via any route)
break *0x0800BCDC
commands
silent
printf "[QGET] cmd_id=%d  value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

break *0x0800BF90
commands
silent
printf "[BF90] sub=1 handler entered ([sp+0]=%d)\n", *(unsigned int*)$sp
continue
end

# Also catch any flow into the IR case body
break *0x0800BF54
commands
silent
printf "[BF54] IR case-body entered, r5=0x%08X (= value passed to notify)\n", $r5
continue
end

printf "\n3 BPs armed: queue-get, IR case-body, IR power-handler.\n"
printf "Press the MUTE button on the IR remote 5 times in the next 60 seconds.\n"
printf "If even ONE press hits anything, we'll see at least one line.\n\n"

monitor resume
shell sleep 60
monitor halt
printf "\nDone listening.\n"
delete breakpoints
monitor resume
quit
