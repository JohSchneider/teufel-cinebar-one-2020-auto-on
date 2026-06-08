set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

# Save current state for restoration
set $save_r0 = $r0
set $save_r1 = $r1
set $save_r2 = $r2
set $save_r3 = $r3
set $save_r4 = $r4
set $save_r5 = $r5
set $save_r6 = $r6
set $save_r7 = $r7
set $save_lr = $lr
set $save_pc = $pc

# Trampoline at 0x20002000 ends in BKPT so we halt after the function returns
set *(unsigned short*)0x20002000 = 0xBE00

# Set BP at the polling-loop's beq (0x0800ED1E). When fired, force r0=1 so
# the loop exits (treats PA0 as LOW).
break *0x0800ED1E
commands
silent
printf "★ Polling loop reached; forcing PA0=LOW exit\n"
set $r0 = 1
continue
end

# Set BP at the EEPROM read site (0x0800ED32) so we can see if it reaches it
break *0x0800ED32
commands
silent
printf "★ Reached EEPROM I2C read! r0=0x%X (=I2C addr), r1=0x%08X\n", $r0, $r1
continue
end

# Jump into the function
printf "\n=== Forcing PC to 0x0800ED10 (polling function entry) ===\n"
set $r0 = 0
set $lr = 0x20002001
set $pc = 0x0800ED10

continue
printf "\nFunction returned. PC=0x%08X r0=0x%08X\n", $pc, $r0

# Restore state
set $r0 = $save_r0
set $r1 = $save_r1
set $r2 = $save_r2
set $r3 = $save_r3
set $r4 = $save_r4
set $r5 = $save_r5
set $r6 = $save_r6
set $r7 = $save_r7
set $lr = $save_lr
set $pc = $save_pc

shell sleep 1
monitor halt
printf "\nFinal: USB clk bit = %d (RCC_APB1ENR = 0x%08X)\n", ((*(unsigned int*)0x4002101C) >> 23) & 1, *(unsigned int*)0x4002101C
printf "PA0 = %d\n", (*(unsigned int*)0x48000010) & 1

delete breakpoints
monitor resume
quit
