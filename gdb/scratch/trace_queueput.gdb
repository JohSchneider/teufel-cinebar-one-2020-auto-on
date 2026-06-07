set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

# BP right after the osMessageQueuePut call (at 0x800bc02 — cmp r0, #0)
delete breakpoints
break *0x0800BC02
commands
silent
printf "INSIDE notify: osMessageQueuePut returned r0=0x%08X  (0=osOK; non-zero=error)\n", $r0
end

# Setup call
set $sr0  = $r0
set $sr1  = $r1
set $sr2  = $r2
set $sr3  = $r3
set $sr12 = $r12
set $slr  = $lr
set $spc  = $pc
set *(unsigned short*)0x20002000 = 0xBE00
set $r0 = 14
set $r1 = 0x202
set $lr = 0x20002001
set $pc = 0x0800BBDC

continue
continue
printf "Done. PC=0x%08X r0(notify ret)=%d\n", $pc, $r0

delete breakpoints
set $r0  = $sr0
set $r1  = $sr1
set $r2  = $sr2
set $r3  = $sr3
set $r12 = $sr12
set $lr  = $slr
set $pc  = $spc
monitor resume
quit
