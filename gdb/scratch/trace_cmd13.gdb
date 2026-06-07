set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Verify state ===\n"
printf "PC=0x%08X state[0]=%d state[+3]=%d\n", $pc, *(unsigned char*)0x200025DC, *(unsigned char*)0x200025DF

# BP at both candidate targets for cmd_id=13 dispatch
break *0x0800BEDA
commands
silent
printf "★ HIT 0x0800BEDA (LIMIT-byte interpretation = cmd 13 → 0x800c32c)\n"
continue
end

break *0x0800BEDC
commands
silent
printf "★ HIT 0x0800BEDC (no-LIMIT interpretation = cmd 13 → IR sub-dispatch → 0x800bf90)\n"
continue
end

break *0x0800BF90
commands
silent
printf "★ HIT 0x0800BF90 (sub=1 = power-toggle handler!)\n"
continue
end

# Inject notify(13, 0x201)
set $sr0=$r0
set $sr1=$r1
set $sr2=$r2
set $sr3=$r3
set $sr12=$r12
set $slr=$lr
set $spc=$pc
set *(unsigned short*)0x20002000 = 0xBE00
set $r0 = 13
set $r1 = 0x201
set $lr = 0x20002001
set $pc = 0x0800BBDC

printf "\n>>> Injecting notify(13, 0x0201) <<<\n"
continue
printf "notify done PC=0x%08X\n", $pc

set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc

monitor resume
shell sleep 2
monitor halt
printf "\nAfter 2s: PC=0x%08X state[0]=%d\n", $pc, *(unsigned char*)0x200025DC

delete breakpoints
monitor resume
quit
