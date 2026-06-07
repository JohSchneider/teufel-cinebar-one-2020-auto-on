set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== Set BP at 0x0800BBEC (right after bl osMemoryPoolAlloc returns) ===\n"
delete breakpoints
break *0x0800BBEC
commands
silent
printf "INSIDE notify: alloc returned r0=0x%08X  (NULL=0x00 = failure)\n", $r0
end

printf "Setting up notify(0, 0) call...\n"
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
# BP halts inside notify; print r0; then continue
continue
# Now should reach BKPT trampoline
printf "After all: PC=0x%08X r0=%d\n", $pc, $r0

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
