set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

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

set *(unsigned short*)0x20002000 = 0xBE00

# BP at the cmp itself (0x0800ED1C) — force r0=1 BEFORE the compare runs
break *0x0800ED1C
commands
silent
set $r0 = 1
continue
end

# Watch progress
break *0x0800ED20
commands
silent
printf "★ Polling exited! Proceeding to EEPROM read sequence\n"
continue
end
break *0x0800ED32
commands
silent
printf "★★ I2C-EEPROM read: r0(devaddr)=0x%02X, r1(buf)=0x%08X, r2(len)=%d\n", $r0, $r1, $r2
continue
end
break *0x0800ED4C
commands
silent
printf "★ EEPROM data validated. r4(buf)=0x%08X, bytes [0..3]=%02X %02X %02X %02X\n", \
  $r4, *(unsigned char*)$r4, *(unsigned char*)($r4+1), *(unsigned char*)($r4+2), *(unsigned char*)($r4+3)
continue
end
break *0x0800ED7E
commands
silent
printf "★ Reached 0x0800ED7E (fail/exit path)\n"
continue
end

set $r0 = 0
set $lr = 0x20002001
set $pc = 0x0800ED10

printf "\n=== Jumping to 0x0800ED10 (PA0-polling function entry) ===\n"
continue
printf "\nFunction returned to BKPT. PC=0x%08X r0=0x%08X\n", $pc, $r0

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
printf "\nFinal RCC_APB1ENR=0x%08X (USB bit23=%d)  USB CNTR=0x%08X  PA0=%d\n", \
  *(unsigned int*)0x4002101C, ((*(unsigned int*)0x4002101C) >> 23) & 1, \
  *(unsigned int*)0x40005C40, (*(unsigned int*)0x48000010) & 1

delete breakpoints
monitor resume
quit
