set confirm off
set pagination off
set remotetimeout 120
target extended-remote :3333
monitor halt
delete breakpoints

# Catch all 4 candidate points
break *0x0800BCDC
commands
silent
printf "★ [QGET] cmd_id=%d  value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

break *0x0800BF54
commands
silent
printf "★ [BF54] case body entered, r5(value)=0x%08X\n", $r5
continue
end

break *0x0800BF90
commands
silent
printf "★ [BF90] sub=1 handler, [sp+0]=%d\n", *(unsigned int*)$sp
continue
end

break *0x0800AB00
commands
silent
printf "★ [POST_EVENT] r0=%d  LR=0x%08X\n", $r0, $lr
continue
end

printf "\n4 BPs armed. Resuming in 3 seconds...\n"
shell sleep 3

monitor resume
shell sleep 2
printf "\n>>>>>> GO! FIRE ARDUINO IR-POWER NOW <<<<<<\n\n"
shell sleep 55
monitor halt
printf "\n>>>>>> Time's up. <<<<<<\n"
delete breakpoints
monitor resume
quit
