set pagination off
set confirm off
target extended-remote :3333

# --- 1. Halt, baseline-snapshot ALL GPIO output state ---
monitor halt

printf "\n=== BASELINE (fw_34 running normally, PA0 HIGH) ===\n"
printf "GPIOA MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000000, *(unsigned int*)0x48000014, *(unsigned int*)0x48000010
printf "GPIOB MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000400, *(unsigned int*)0x48000414, *(unsigned int*)0x48000410
printf "GPIOC MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000800, *(unsigned int*)0x48000814, *(unsigned int*)0x48000810
printf "GPIOD MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000c00, *(unsigned int*)0x48000c14, *(unsigned int*)0x48000c10
printf "GPIOF MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48001400, *(unsigned int*)0x48001414, *(unsigned int*)0x48001410
printf "RCC_AHBENR  = 0x%08x   APB1ENR = 0x%08x   APB2ENR = 0x%08x\n", *(unsigned int*)0x40021014, *(unsigned int*)0x4002101c, *(unsigned int*)0x40021018

# Also snapshot the service-thread state struct at 0x2000243c
printf "Thread state @ 0x2000243C: %08x %08x %08x %08x\n", *(unsigned int*)0x2000243c, *(unsigned int*)0x20002440, *(unsigned int*)0x20002444, *(unsigned int*)0x20002448
printf "Thread state +20:           %08x %08x %08x %08x\n", *(unsigned int*)0x2000244c, *(unsigned int*)0x20002450, *(unsigned int*)0x20002454, *(unsigned int*)0x20002458

# --- 2. Set HBP at read_pa0()'s cmp instruction, override r0=0 (= "LOW") ---
printf "\n=== Installing HBP at 0x0800F148 (cmp r0,#0 in read_pa0) ===\n"
hbreak *0x0800F148
commands
  silent
  set $r0 = 0
  continue
end

# --- 3. Resume; let the service thread iterate several times ---
printf "\n=== Resuming for 3 seconds... ===\n"
monitor resume

shell sleep 3

# --- 4. Halt and snapshot again ---
monitor halt

printf "\n=== AFTER 3s with read_pa0 forced LOW ===\n"
printf "GPIOA MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000000, *(unsigned int*)0x48000014, *(unsigned int*)0x48000010
printf "GPIOB MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000400, *(unsigned int*)0x48000414, *(unsigned int*)0x48000410
printf "GPIOC MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000800, *(unsigned int*)0x48000814, *(unsigned int*)0x48000810
printf "GPIOD MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48000c00, *(unsigned int*)0x48000c14, *(unsigned int*)0x48000c10
printf "GPIOF MODER = 0x%08x   ODR = 0x%08x   IDR = 0x%08x\n", *(unsigned int*)0x48001400, *(unsigned int*)0x48001414, *(unsigned int*)0x48001410
printf "RCC_AHBENR  = 0x%08x   APB1ENR = 0x%08x   APB2ENR = 0x%08x\n", *(unsigned int*)0x40021014, *(unsigned int*)0x4002101c, *(unsigned int*)0x40021018
printf "Thread state @ 0x2000243C: %08x %08x %08x %08x\n", *(unsigned int*)0x2000243c, *(unsigned int*)0x20002440, *(unsigned int*)0x20002444, *(unsigned int*)0x20002448
printf "Thread state +20:           %08x %08x %08x %08x\n", *(unsigned int*)0x2000244c, *(unsigned int*)0x20002450, *(unsigned int*)0x20002454, *(unsigned int*)0x20002458
printf "PC (was where when we halted) = 0x%08x\n", $pc

# --- 5. Clean up: remove the BP and let the bar continue normally ---
delete breakpoints
printf "\n=== HBP removed; bar resumes with normal PA0 behavior ===\n"
monitor resume
quit
