set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== Test notify(13, 0x202) — IR channel ===\n"
printf "BEFORE: state[0] = %d, PC=0x%08X\n", *(unsigned char*)0x200025DC, $pc

delete breakpoints
# Sub=2 handler at 0x0800BF90 (POWER toggle code)
break *0x0800BF90
commands
silent
printf "★ Hit sub=2 handler! [sp+0]=%d should be 2 to proceed.\n", *(unsigned int*)$sp
continue
end
# Inside the toggle path — should call post_event_type0(1 or 2)
break *0x0800BFAA
commands
silent
printf "★★ About to call post_event_type0(action=%d) — TOGGLE FIRING!\n", $r0
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
set $r0 = 13
set $r1 = 0x202
set $lr = 0x20002001
set $pc = 0x0800BBDC

continue
printf "notify completed (BKPT), PC=0x%08X r0=%d\n", $pc, $r0
set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc

# Don't delete BPs yet — leave them armed during resume
monitor resume
shell sleep 3
monitor halt
printf "AFTER 3s: state[0]=%d PC=0x%08X (note: if state went 2→1 or 1→2, the toggle worked!)\n", *(unsigned char*)0x200025DC, $pc

delete breakpoints
monitor resume
quit
