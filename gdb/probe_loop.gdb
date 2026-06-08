set pagination off
set confirm off
target extended-remote :3333

monitor halt

# Halt PC sampling: take 5 snapshots over 1 second
printf "\n=== PC samples (is the service thread even running?) ===\n"

set $i = 0
while $i < 5
  monitor resume
  shell sleep 0.2
  monitor halt
  printf "Sample %d: PC=0x%08x  LR=0x%08x  CONTROL=0x%x\n", $i, $pc, $lr, $control
  set $i = $i + 1
end

# Try BP at the LOOP HEAD (osDelay call) — if it fires, the thread is alive
printf "\n=== HBP at 0x800e936 (top of polling loop) ===\n"
hbreak *0x0800e936
commands
  silent
  printf "LOOP-TOP hit\n"
  continue
end
monitor resume
shell sleep 2
monitor halt
delete breakpoints

# Try BP at the HIGH path's osDelay (0x800eae8)
printf "\n=== HBP at 0x800eae8 (osDelay in HIGH path) ===\n"
hbreak *0x0800eae8
commands
  silent
  printf "HIGH-PATH-DELAY hit\n"
  continue
end
monitor resume
shell sleep 2
monitor halt
delete breakpoints

# Try BP at 0x800e928 (thread entry — should only fire ONCE at boot, but if thread restarts...)
printf "\n=== HBP at 0x800e928 (thread entry) ===\n"
hbreak *0x0800e928
commands
  silent
  printf "THREAD-ENTRY hit\n"
  continue
end
monitor resume
shell sleep 1
monitor halt
delete breakpoints

# Snapshot one more PC reading
printf "\nFinal PC: 0x%08x\n", $pc

monitor resume
quit
