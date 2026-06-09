set confirm off
set pagination off
target extended-remote :3333

# Connect; bar is running. Halt.
monitor halt
flushregs
printf "Idle PC = 0x%x\n", $pc

# Set BP at a function that runs frequently — osKernelGetTickCount at 0x800d66c
# This is called by the bar many times per second (per our earlier samples)
hbreak *0x0800d66c
commands
  silent
  printf "[TICK_BP] hit\n"
  continue
end

monitor resume
shell sleep 1
monitor halt
flushregs
printf "After 1s with BP at osKernelGetTickCount: PC=0x%x\n", $pc

delete breakpoints
monitor resume
detach
quit
