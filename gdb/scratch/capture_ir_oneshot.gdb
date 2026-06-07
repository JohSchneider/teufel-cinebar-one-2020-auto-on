set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints
break *0x0800AB00
commands
silent
printf "\n========== IR EVENT CAPTURED ==========\n"
printf "r0 (action arg) = 0x%08X (%d)\n", $r0, $r0
printf "lr (return addr) = 0x%08X\n", $lr
printf "sp = 0x%08X\n", $sp
printf "r1=0x%08X r2=0x%08X r3=0x%08X\n", $r1, $r2, $r3
printf "r4=0x%08X r5=0x%08X r6=0x%08X r7=0x%08X\n", $r4, $r5, $r6, $r7
printf "\nStack (sp..sp+31):\n"
x/8wx $sp
printf "\nCaller disasm (lr-32 .. lr):\n"
x/8i $lr-32
printf "\nDeleting breakpoint, continuing...\n"
delete breakpoints
continue
end
continue
