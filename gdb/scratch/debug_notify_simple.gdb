set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== Test notify(0, 0) — the boot-shim's call pattern ===\n"
printf "g_notify_struct head bytes:\n"
x/4wx 0x200023BC
printf "\n"
set $sr0  = $r0
set $sr1  = $r1
set $sr2  = $r2
set $sr3  = $r3
set $sr12 = $r12
set $slr  = $lr
set $spc  = $pc
set *(unsigned short*)0x20002000 = 0xBE00
set $r0 = 0
set $r1 = 0
set $lr = 0x20002001
set $pc = 0x0800BBDC
continue
printf "notify(0,0) returned r0=%d  (0=success, 1=fail)\n", $r0
set $r0  = $sr0
set $r1  = $sr1
set $r2  = $sr2
set $r3  = $sr3
set $r12 = $sr12
set $lr  = $slr
set $pc  = $spc

printf "\n=== Test 2: notify(14, 0) — minimum IR-channel call ===\n"
set $sr0  = $r0
set $sr1  = $r1
set $sr2  = $r2
set $sr3  = $r3
set $sr12 = $r12
set $slr  = $lr
set $spc  = $pc
set $r0 = 14
set $r1 = 0
set $lr = 0x20002001
set $pc = 0x0800BBDC
continue
printf "notify(14,0) returned r0=%d\n", $r0
set $r0  = $sr0
set $r1  = $sr1
set $r2  = $sr2
set $r3  = $sr3
set $r12 = $sr12
set $lr  = $slr
set $pc  = $spc

monitor resume
quit
