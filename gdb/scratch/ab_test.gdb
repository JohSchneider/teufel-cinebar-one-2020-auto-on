set confirm off
set pagination off
set remotetimeout 90
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Pre-flight ===\n"
printf "  PC=0x%08X state=%d  0xBFAA=0x%04X (need 0xBF00 nop)\n", $pc, *(unsigned char*)0x200025DC, *(unsigned short*)0x0800BFAA

break *0x0800BCDC
commands
silent
printf "[QGET]   cmd_id=%d value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end
break *0x0800BF54
commands
silent
printf "[BF54]   r5=0x%08X\n", $r5
continue
end
break *0x0800BF90
commands
silent
printf "[BF90]   [sp+0]=%d\n", *(unsigned int*)$sp
continue
end
break *0x0800AB00
commands
silent
printf "[POSTEVT] r0=%d LR=0x%08X\n", $r0, $lr
continue
end

printf "\n>>>> PART A: Fire Arduino IR-power 1-2 times during next 25s. <<<<\n"
monitor resume
shell sleep 25
monitor halt
printf "\n--- End of Part A ---\n"

printf "\n>>>> PART B: Now injecting notify(12, 0x0201) via GDB <<<<\n"
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
printf "notify injection finished. PC=0x%08X\n", $pc
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
printf "\n--- End of Part B ---\n"
printf "PC=0x%08X state=%d\n", $pc, *(unsigned char*)0x200025DC

delete breakpoints
monitor resume
quit
