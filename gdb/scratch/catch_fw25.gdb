set confirm off
set pagination off
set remotetimeout 90
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Pre-flight ===\n"
printf "  PC = 0x%08X  (need 0x08010AB6 = idle)\n", $pc
printf "  state[0] = %d  (need 2 = active)\n", *(unsigned char*)0x200025DC
printf "  0x0800BFAA = 0x%04X 0x%04X  (need 0xBF00 0xBF00 = nop nop)\n", *(unsigned short*)0x0800BFAA, *(unsigned short*)0x0800BFAC

break *0x0800BCDC
commands
silent
printf "★ [QGET]   cmd_id=%d  value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

break *0x0800BF54
commands
silent
printf "★ [BF54]   IR case body, r5(value)=0x%08X\n", $r5
continue
end

break *0x0800BF90
commands
silent
printf "★ [BF90]   sub=1 (POWER) handler, [sp+0]=%d\n", *(unsigned int*)$sp
continue
end

break *0x0800AB00
commands
silent
printf "★ [POSTEVT] r0=%d  LR=0x%08X  (would-be standby trigger)\n", $r0, $lr
continue
end

printf "\n4 BPs armed.  Fire Arduino IR-power 1-2 times in the next 45s.\n\n"

monitor resume
shell sleep 45
monitor halt
printf "\nDone. PC = 0x%08X  state[0] = %d\n", $pc, *(unsigned char*)0x200025DC
delete breakpoints
monitor resume
quit
