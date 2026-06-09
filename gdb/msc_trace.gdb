set confirm off
set pagination off
target extended-remote :3333
monitor halt

# Clear any existing BPs
monitor bp

# Set HBPs via OpenOCD's native bp command
# WRITE(10) handler entry — capture r0/r1/r2 (state struct + buffer + ...)
monitor bp 0x08002CA6 2 hw

# First virtual dispatch (validate?)
monitor bp 0x08002CD6 2 hw

# Second virtual dispatch (do_write?)
monitor bp 0x08002CEE 2 hw

# Flash unlock entry — if reached, we're flashing
monitor bp 0x08000B0C 2 hw

monitor bp

printf "\nBPs installed. Resuming bar...\n"
monitor resume

printf "\n=== NOW, on the HOST side: do `echo X > /media/johannes/Teufel\\ CBO/test.txt; sync`\n"
printf "=== Then wait — BPs will catch the write. Sleeping 10s...\n"
shell sleep 10

monitor halt
flushregs
printf "\nAfter 10s: PC = 0x%x  LR = 0x%x\n", $pc, $lr
printf "r0=%x r1=%x r2=%x r3=%x r4=%x r5=%x r6=%x r7=%x\n", $r0, $r1, $r2, $r3, $r4, $r5, $r6, $r7

monitor resume
detach
quit
