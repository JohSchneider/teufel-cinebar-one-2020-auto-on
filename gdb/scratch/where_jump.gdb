set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints

# BP right before the bx r3 — capture the target address
break *0x080108FA
commands
silent
printf "[helper-pre-bx] r3(target)=0x%08X  LR_v=0x%08X  (called from BL at LR_v-5)\n", $r3, $lr
continue
end

# Also QGET for sanity
break *0x0800BCDC
commands
silent
printf "[QGET] cmd_id=%d value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

# Inject notify(12, 0x0201)
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
printf "\nnotify done, PC=0x%08X\n", $pc

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
delete breakpoints
monitor resume
quit
