set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt

printf "Current PC = 0x%08X\n", $pc

# Skip the polling loop by setting PC to right after it
set $pc = 0x0800ED20

# Set BPs to track progress
delete breakpoints
break *0x0800ED32
commands
silent
printf "★ At I2C-EEPROM call: r0=0x%02X r1=0x%08X r2=%d\n", $r0, $r1, $r2
continue
end
break *0x0800ED4C
commands
silent
printf "★★ EEPROM validated! buf=0x%08X bytes: %02X %02X %02X %02X %02X %02X %02X %02X\n", \
  $r4, *(unsigned char*)$r4, *(unsigned char*)($r4+1), *(unsigned char*)($r4+2), \
  *(unsigned char*)($r4+3), *(unsigned char*)($r4+4), *(unsigned char*)($r4+5), \
  *(unsigned char*)($r4+6), *(unsigned char*)($r4+7)
continue
end
break *0x0800ED7E
commands
silent
printf "✗ Reached fail/exit path at 0x0800ED7E (validation/I2C failed)\n"
continue
end

monitor resume
shell sleep 3
monitor halt
printf "\nAfter 3s — PC=0x%08X (LR=0x%08X)\n", $pc, $lr
printf "RCC_APB1ENR=0x%08X (USB bit23=%d)\n", *(unsigned int*)0x4002101C, ((*(unsigned int*)0x4002101C) >> 23) & 1
printf "I2C1 CR1=0x%08X  ISR=0x%08X\n", *(unsigned int*)0x40005400, *(unsigned int*)0x40005418

delete breakpoints
monitor resume
quit
