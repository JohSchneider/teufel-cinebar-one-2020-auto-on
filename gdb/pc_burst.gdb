set pagination off
set confirm off
target extended-remote :3333
monitor halt

set $i = 0
set $hits_idle = 0
set $hits_other = 0
while $i < 30
  monitor resume
  shell sleep 0.05
  monitor halt
  if $pc == 0x08010ab6
    set $hits_idle = $hits_idle + 1
  else
    set $hits_other = $hits_other + 1
    printf "Sample %d non-idle: PC=0x%08x  LR=0x%08x\n", $i, $pc, $lr
  end
  set $i = $i + 1
end

printf "\nSummary: %d samples at idle, %d samples elsewhere\n", $hits_idle, $hits_other

# Also dump the RTX thread list pointer to see how many threads are active
# osRtxInfo @ 0x20002538; thread.run (current_running) is at offset 36 typically
printf "\nosRtxInfo dump (first 64 bytes):\n"
set $j = 0
while $j < 16
  printf "  +0x%02x: 0x%08x\n", $j*4, *(unsigned int*)(0x20002538 + $j*4)
  set $j = $j + 1
end

monitor resume
quit
