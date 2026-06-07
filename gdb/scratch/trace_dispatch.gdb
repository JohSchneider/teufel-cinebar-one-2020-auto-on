set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

# Set BP at case-14 sub=2 handler (the toggle target)
delete breakpoints
break *0x0800BF90
commands
silent
printf "DISPATCH REACHED sub=2 handler @0x800BF90; r5=0x%08X [sp+0]=%d\n", $r5, *(unsigned int*)$sp
end

# Also bp at dispatch task message-receive point — see msg.byte[0] right after get
break *0x0800BCDC
commands
silent
printf "DISPATCH msg received: msg.byte[0]=%d (cmd_id), msg.word[1]=0x%08X (value)\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end

printf "BPs armed: 0x800BCDC (msg get) and 0x800BF90 (sub=2 reached)\n"

# Post a notify(14, 0x202) and resume
set $sr0=$r0
set $sr1=$r1
set $sr2=$r2
set $sr3=$r3
set $sr12=$r12
set $slr=$lr
set $spc=$pc
set *(unsigned short*)0x20002000 = 0xBE00
set $r0 = 14
set $r1 = 0x202
set $lr = 0x20002001
set $pc = 0x0800BBDC

continue
# After notify completes (BKPT), restore + run for a few sec
printf "notify done, PC=0x%08X r0=%d\n", $pc, $r0
set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc
delete breakpoints
break *0x0800BCDC
commands
silent
printf "DISPATCH msg received: cmd_id=%d value=0x%08X\n", *(unsigned char*)$r1, *(unsigned int*)($r1+4)
continue
end
break *0x0800BF90
commands
silent
printf "DISPATCH REACHED sub=2 @0x800BF90; r5=0x%08X [sp+0]=%d\n", $r5, *(unsigned int*)$sp
end

monitor resume
shell sleep 3
monitor halt
printf "Final PC=0x%08X  state[0]=%d\n", $pc, *(unsigned char*)0x200025DC
delete breakpoints
monitor resume
quit
