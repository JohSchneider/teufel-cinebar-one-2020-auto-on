set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== BEFORE call ===\n"
printf "PC = 0x%08X\n", $pc
printf "PSP = 0x%08X\n", $sp
printf "state[0]= %d (1=standby, 2=active)\n", *(unsigned char*)0x200025DC

printf "\n--- g_notify_struct contents (queue handles, pool ptrs) ---\n"
x/8wx 0x200023BC

printf "\n=== Saving regs, setting up notify(14, 0x0202) call ===\n"
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
printf "After continue: PC=0x%08X  r0=0x%08X (notify return: 0=success, 1=failure)\n", $pc, $r0

printf "\n=== Restoring + resuming ===\n"
set $r0  = $sr0
set $r1  = $sr1
set $r2  = $sr2
set $r3  = $sr3
set $r12 = $sr12
set $lr  = $slr
set $pc  = $spc
monitor resume

# Let the dispatch task pick up the message
shell sleep 2

printf "\n=== AFTER 2 sec ===\n"
monitor halt
printf "PC = 0x%08X\n", $pc
printf "state[0]= %d (was the bar's state changed?)\n", *(unsigned char*)0x200025DC

monitor resume
quit
