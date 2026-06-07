set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints
break *0x0800BBDC if $r0 == 2
commands
silent
printf "\n========== notify(channel=2, value=0x%08X) CAPTURED ==========\n", $r1
printf "lr (caller return) = 0x%08X\n", $lr
printf "sp = 0x%08X\n", $sp
printf "r0=0x%08X r1=0x%08X r2=0x%08X r3=0x%08X\n", $r0, $r1, $r2, $r3
printf "r4=0x%08X r5=0x%08X r6=0x%08X r7=0x%08X\n", $r4, $r5, $r6, $r7
printf "\nStack (sp..sp+47):\n"
x/12wx $sp
printf "\nCaller disasm (lr-48 .. lr):\n"
x/12i $lr-48
printf "\nDeleting breakpoint, continuing...\n"
delete breakpoints
continue
end
continue
