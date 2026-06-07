set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Verify notify(12, 0x0201) — corrected IR power ===\n"
printf "BEFORE: state[0] = %d\n", *(unsigned char*)0x200025DC

break *0x0800BF90
commands
silent
printf "★ Hit sub=1 power-handler at 0x800BF90! [sp+0]=%d (need 2)\n", *(unsigned int*)$sp
continue
end
break *0x0800BFAA
commands
silent
printf "★★ About to bl post_event_type0(%d) — toggle FIRING!\n", $r0
continue
end

set $sr0=$r0
set $sr1=$r1
set $sr2=$r2
set $sr3=$r3
set $sr12=$r12
set $slr=$lr
set $spc=$pc
set *(unsigned short*)0x20002000 = 0xBE00
set $r0 = 12
set $r1 = 0x201
set $lr = 0x20002001
set $pc = 0x0800BBDC
continue
printf "notify done. PC=0x%08X\n", $pc
set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc

monitor resume
shell sleep 3
monitor halt
printf "\nAFTER 3s: state[0] = %d  (★ toggled if went 2→1 or 1→2)\n", *(unsigned char*)0x200025DC
delete breakpoints
monitor resume
quit
