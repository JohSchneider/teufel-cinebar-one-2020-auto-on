set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

# BP at the cmp right after HAL_GPIO_ReadPin returns the PA0 value.
# We'll force r0 = 0 here, which makes the function return 1 (PA0 was LOW),
# which makes the caller enter the special path at 0x0800E944.
break *0x0800F148
commands
silent
printf "★ PA0 check fired. Original HAL_GPIO_ReadPin returned r0=%d (1=PA0 HIGH=normal, 0=PA0 LOW=special)\n", $r0
printf "   Forcing r0=0 (pretend PA0 is LOW) and continuing...\n"
set $r0 = 0
continue
end

# Also watch for HardFault or unexpected state
break *0x0800F15C
commands
silent
printf "✗ Hit BKPT trap at 0x0800F15C — defensive bkpt instruction\n"
end

# Reset and run from boot — the PA0 check fires within first ~100 ms
printf "\n=== Resetting bar and watching for PA0 check ===\n"
monitor reset halt
monitor reset run

# Give it time to boot + reach + pass the BP
shell sleep 5
monitor halt
printf "\n=== State 5s after override ===\n"
printf "  PC = 0x%08X\n", $pc
printf "  state[0] (power) = %d\n", *(unsigned char*)0x200025DC
printf "  RCC_APB1ENR = 0x%08X  (bit 23 = USB clk; should be 1 if USB enabled)\n", *(unsigned int*)0x4002101C
printf "  USB CNTR (0x40005C40) = 0x%08X\n", *(unsigned int*)0x40005C40
printf "  GPIOA IDR = 0x%08X (PA0 bit 0)\n", *(unsigned int*)0x48000010

delete breakpoints
monitor resume
quit
