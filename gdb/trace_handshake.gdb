set pagination off
set confirm off
target extended-remote :3333
monitor halt

# Multi-BP trace through the LOW path
# 0x800e944 = LOW path entry (state[+8]=2 here)
# 0x800e980 = main service work entry (first time)
# 0x800ed10 = handshake entry
# 0x800ed20 = polling exited, about to delay 100ms
# 0x800ed32 = about to call i2c_write
# 0x800ed3c = about to call i2c_read
# 0x800ed42 = after i2c_read, check result

hbreak *0x800e944
commands
  silent
  printf "[1] LOW-path entry @ 0x800e944\n"
  continue
end

hbreak *0x800ed10
commands
  silent
  printf "[2] handshake entry @ 0x800ed10\n"
  continue
end

hbreak *0x800ed20
commands
  silent
  printf "[3] polling exited, 100ms delay next @ 0x800ed20\n"
  continue
end

hbreak *0x800ed32
commands
  silent
  printf "[4] before i2c_write @ 0x800ed32, retry r7=%d\n", $r7
  continue
end

# Save & drive PA0
set $orig_moder = *(unsigned int*)0x48000000
set $orig_odr   = *(unsigned int*)0x48000014
set *(unsigned int*)0x48000014 = $orig_odr & ~0x1
set *(unsigned int*)0x48000000 = ($orig_moder & ~0x3) | 0x1

printf "\n=== PA0 driven LOW, running 5s ===\n"
monitor resume
shell sleep 5
monitor halt

# Snapshot I²C handle state at halt
printf "\nAt halt:\n"
printf "  PC = 0x%08x\n", $pc
printf "  I²C2 handle @ 0x20002734: instance=0x%08x state=0x%02x\n", *(unsigned int*)0x20002734, *(unsigned char*)0x20002775
printf "  I²C2 CR1=0x%08x  CR2=0x%08x  ISR=0x%08x\n", *(unsigned int*)0x40005800, *(unsigned int*)0x40005804, *(unsigned int*)0x40005818
printf "  GPIOB AFRH (PB8-15 alt-function regs) = 0x%08x\n", *(unsigned int*)0x48000424

delete breakpoints
set *(unsigned int*)0x48000000 = $orig_moder
set *(unsigned int*)0x48000014 = $orig_odr
monitor resume
quit
