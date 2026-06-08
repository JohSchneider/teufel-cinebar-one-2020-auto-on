set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

# Watch for entry into 0x0800ED10 (the PA0-polling function)
break *0x0800ED10
commands
silent
printf "★★ HIT 0x0800ED10 (PA0-polling entry)! Bar is entering service mode.\n"
continue
end

# Also watch the PA0 read site (one-shot check)
break *0x0800F13C
commands
silent
printf "★ HIT 0x0800F13C (PA0 read function) called from LR=0x%08X\n", $lr
continue
end

# Make sure they survive a reset
monitor reset halt
monitor reset run

printf "\n=== Reset bar, watching for PA0-related code paths for 10s ===\n"
shell sleep 10
monitor halt

printf "\n=== After 10s of observation ===\n"
printf "  PC = 0x%08X  state[0] = %d\n", $pc, *(unsigned char*)0x200025DC
printf "  GPIOA IDR = 0x%08X (PA0 bit = %d)\n", *(unsigned int*)0x48000010, (*(unsigned int*)0x48000010) & 1

delete breakpoints
monitor resume
quit
