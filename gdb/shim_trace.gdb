set confirm off
set pagination off
target extended-remote :3333

monitor reset halt

hbreak *0x0801E880
commands
  silent
  printf "[SHIM_ENTRY] APB1ENR before = 0x%08x  r0=%x r1=%x lr=%x\n", *(unsigned int*)0x4002101c, $r0, $r1, $lr
  continue
end

hbreak *0x0801E896
commands
  silent
  printf "[SHIM_EXIT]  APB1ENR after = 0x%08x\n", *(unsigned int*)0x4002101c
  continue
end

monitor resume
shell sleep 4
monitor halt

# Re-read state explicitly
flushregs
printf "Final: PC=0x%x  APB1ENR=0x%08x\n", $pc, *(unsigned int*)0x4002101c

delete breakpoints
monitor resume
detach
quit
