set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Bar state at start ===\n"
printf "PC=0x%08X  state[0..7] = %d %d %d %d %d %d %d %d\n", $pc, *(unsigned char*)0x200025DC, *(unsigned char*)0x200025DD, *(unsigned char*)0x200025DE, *(unsigned char*)0x200025DF, *(unsigned char*)0x200025E0, *(unsigned char*)0x200025E1, *(unsigned char*)0x200025E2, *(unsigned char*)0x200025E3

# === CHECK 1: trace cmd_id=13 dispatch target ===
break *0x0800BEDA
commands
silent
printf "★ HIT 0x0800BEDA  (LIMIT-byte interpretation = goes to 0x800c32c)\n"
continue
end
break *0x0800BEDC
commands
silent
printf "★ HIT 0x0800BEDC  (no-LIMIT interpretation = IR sub-dispatch)\n"
continue
end
break *0x0800BF90
commands
silent
printf "★ HIT 0x0800BF90  (sub=1 power-toggle handler!)\n"
continue
end
break *0x0800C32C
commands
silent
printf "★ HIT 0x0800C32C  (source-gated handler entry)\n"
continue
end

# Inject notify(13, 0x201) via BKPT trampoline
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
printf "notify returned. PC=0x%08X\n", $pc

set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc

monitor resume
shell sleep 1
monitor halt
printf "\n=== State after 1s ===\n"
printf "PC=0x%08X  state[0..7] = %d %d %d %d %d %d %d %d\n", $pc, *(unsigned char*)0x200025DC, *(unsigned char*)0x200025DD, *(unsigned char*)0x200025DE, *(unsigned char*)0x200025DF, *(unsigned char*)0x200025E0, *(unsigned char*)0x200025E1, *(unsigned char*)0x200025E2, *(unsigned char*)0x200025E3
delete breakpoints
monitor resume
quit
