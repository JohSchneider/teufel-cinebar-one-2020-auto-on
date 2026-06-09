set confirm off
set pagination off
target extended-remote :3333

monitor reset halt

# BPs along main()'s expected path
hbreak *0x080039D4
commands
  silent
  printf "[MAIN_ENTRY]\n"
  continue
end

hbreak *0x08003A6C
commands
  silent
  printf "[BEFORE_PA1_READ] r0=%x r1=%x (HAL_GPIO_ReadPin called next)\n", $r0, $r1
  continue
end

hbreak *0x08003AB2
commands
  silent
  printf "[WAIT_LOOP_TOP] (polling PA1; we should see this only a few times if PA1 idle HIGH)\n"
  continue
end

hbreak *0x08003AD0
commands
  silent
  printf "[BL_PATCHED_SITE] reached — our shim should now run\n"
  continue
end

monitor resume
shell sleep 4
monitor halt

flushregs
printf "Final: PC=0x%x  APB1ENR=0x%08x\n", $pc, *(unsigned int*)0x4002101c

delete breakpoints
monitor resume
detach
quit
