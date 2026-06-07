set confirm off
set pagination off
set remotetimeout 90
target extended-remote :3333
monitor halt
delete breakpoints

break *0x0800BCDC
commands
silent
printf "[QGET] cmd_id=%d  value=0x%08X  ← real IR press caught\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

break *0x0800BF54
commands
silent
printf "[BF54 case-12 entered] r5=0x%08X\n", $r5
continue
end

break *0x0800BF90
commands
silent
printf "[BF90 sub=1 power handler] [sp+0]=%d\n", *(unsigned int*)$sp
continue
end

printf "\n3 BPs armed: queue-get, IR case-body, IR power-handler.\n"
printf "Fire the Arduino IR-power code now. 45 seconds.\n\n"

monitor resume
shell sleep 45
monitor halt
printf "\nDone.\n"
delete breakpoints
monitor resume
quit
