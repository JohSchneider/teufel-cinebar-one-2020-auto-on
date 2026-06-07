set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor reset halt
monitor reset run
shell sleep 6
monitor halt
delete breakpoints

printf "\n=== After fresh reset; bar should be active ===\n"
printf "state[0] = %d, PC = 0x%08X\n", *(unsigned char*)0x200025DC, $pc

# No BPs this time. Just call notify(12, 0x0201) and observe.
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
printf "notify done PC=0x%08X\n", $pc
set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc

monitor resume
shell sleep 4
monitor halt
printf "After 4s: state[0]=%d  PC=0x%08X (0x0800f15c = HardFault handler)\n", *(unsigned char*)0x200025DC, $pc

monitor resume
quit
