set pagination off
set confirm off
target extended-remote :3333
monitor halt

# CEC queue handles area
printf "\n=== CEC queue handles @ 0x20002518 ===\n"
printf "  RX handle (+4) = 0x%08x   TX handle (+8) = 0x%08x\n", *(unsigned int*)0x2000251c, *(unsigned int*)0x20002520

# Set BP at CEC RX dispatcher and TX poller — see if they fire
hbreak *0x800eb04
commands
  silent
  printf "[CEC_RX_dispatcher fired]\n"
  continue
end

hbreak *0x800edf0
commands
  silent
  printf "[CEC_TX_poller fired]\n"
  continue
end

monitor resume
shell sleep 1
monitor halt

printf "\n(If lines above show, CEC handler thread IS alive in normal operation)\n"

delete breakpoints
monitor resume
detach
quit
