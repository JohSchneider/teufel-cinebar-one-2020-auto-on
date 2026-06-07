set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== Test the corrected cmd_id=13 (IR channel) with sub=2 (power) ===\n"
printf "BEFORE: state[0] = %d\n", *(unsigned char*)0x200025DC

delete breakpoints
break *0x0800BF90
commands
silent
printf "★ DISPATCH REACHED sub=2 (POWER handler) — toggle should fire!\n"
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
printf "notify done, PC=0x%08X\n", $pc
set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc
delete breakpoints
monitor resume
shell sleep 2
monitor halt
printf "AFTER 2s:  state[0] = %d  (was 2 if active; should be 1 if power toggled to standby)\n", *(unsigned char*)0x200025DC
monitor resume
quit
