set pagination off
set confirm off
target extended-remote :3333
monitor halt

# Probe CEC handle storage AND queue handles
printf "=== CEC handle struct at 0x200026F8 (cec_peripheral_init writes here) ===\n"
set $i = 0
while $i < 12
  printf "  +0x%02x: 0x%08x\n", $i*4, *(unsigned int*)(0x200026F8 + $i*4)
  set $i = $i + 1
end

printf "\n=== Queue handles at 0x20002518 ===\n"
set $i = 0
while $i < 6
  printf "  +0x%02x: 0x%08x\n", $i*4, *(unsigned int*)(0x20002518 + $i*4)
  set $i = $i + 1
end

# Set BP at CEC RX dispatcher
printf "\n=== Set BP at 0x800eb04 (CEC RX dispatcher) and 0x800edf0 (TX poller) ===\n"
hbreak *0x800eb04
commands
  silent
  printf "[%d] CEC_RX hit\n", *(unsigned int*)0x20002538+12
  continue
end
hbreak *0x800edf0
commands
  silent
  printf "[%d] CEC_TX hit\n", *(unsigned int*)0x20002538+12
  continue
end

monitor resume
shell sleep 3
monitor halt
printf "\n(If lines above show, CEC thread is firing every ~50ms)\n"

delete breakpoints
monitor resume
detach
quit
