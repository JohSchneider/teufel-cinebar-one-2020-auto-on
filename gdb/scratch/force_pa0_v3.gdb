set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "Initial state: PC=0x%08X (bar may be stuck in polling loop)\n", $pc

# Force r0=1 just before the cmp, so loop exits naturally
break *0x0800ED1C
commands
silent
set $r0 = 1
continue
end

# Two other BPs to track progress
break *0x0800ED32
commands
silent
printf "★ I2C-EEPROM read: dev=0x%02X, buf=0x%08X, len=%d\n", $r0, $r1, $r2
continue
end
break *0x0800ED4C
commands
silent
printf "★ EEPROM validated. buf=0x%08X bytes[0..3]: %02X %02X %02X %02X\n", \
  $r4, *(unsigned char*)$r4, *(unsigned char*)($r4+1), *(unsigned char*)($r4+2), *(unsigned char*)($r4+3)
continue
end

monitor resume
shell sleep 3
monitor halt
printf "\nAfter 3s — PC=0x%08X\n", $pc
printf "RCC_APB1ENR=0x%08X (USB bit23=%d)  USB CNTR=0x%08X\n", \
  *(unsigned int*)0x4002101C, ((*(unsigned int*)0x4002101C) >> 23) & 1, *(unsigned int*)0x40005C40
printf "RAM at 0x20002??? (likely EEPROM buffer):\n"
x/4xw 0x200024D8

delete breakpoints
monitor resume
quit
