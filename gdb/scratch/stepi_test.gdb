set confirm off
set pagination off
target extended-remote :3333
monitor reset halt
flushregs
printf "PC=0x%x\n", $pc
stepi
flushregs
printf "After stepi: PC=0x%x\n", $pc
stepi
flushregs
printf "After 2nd stepi: PC=0x%x\n", $pc
stepi
flushregs
printf "After 3rd stepi: PC=0x%x\n", $pc
detach
quit
