set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== Full dispatch trace for notify(13, 0x202) ===\n"
delete breakpoints

# 4 BPs (max for Cortex-M0 FPB)
break *0x0800BCDC
commands
silent
printf "1. msg get: cmd_id=%d value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

break *0x0800BEDC
commands
silent
printf "2. case 13 entry reached (r5=0x%08X)\n", $r5
continue
end

break *0x0800BF64
commands
silent
printf "3. about to bl 0x80108e2 (sub-dispatch); r3 (sub-idx) = %d, [sp+0]=%d\n", $r3, *(unsigned int*)$sp
continue
end

break *0x0800BF90
commands
silent
printf "4. ★ sub=2 reached!\n"
continue
end

# Setup the notify call
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
printf "notify completed, PC=0x%08X r0=%d\n", $pc, $r0
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
printf "\nFinal state[0] = %d\n", *(unsigned char*)0x200025DC
delete breakpoints
monitor resume
quit
