set pagination off
set confirm off
target extended-remote :3333
monitor halt

printf "\n=== Strategy: BP just after the I²C read returns; capture result + buffer ===\n"
# 0x0800ED3C: bl 0x800f0ac (i2c_read)
# 0x0800ED40: adds r7, r7, #1
# 0x0800ED42: cmp r0, #0     ← r0 = I²C return (0=success, 1=NACK/timeout)
# 0x0800ED44: beq.n 0x800ed4c   ← if r0==0 (success), go validate bytes
# r4 = buffer base for received bytes (set earlier at ldr r4, [pc, #116] @ (0x800ed9c))
# 0x800ed9c literal = 0x20002792 (from disasm)

# Set BP at 0x800ED42 (right after I²C read, before the cmp) — capture state
hbreak *0x0800ED42
commands
  silent
  printf "==> I²C read returned: r0=%d (0=success), retry r7=%d, buf @ 0x%08x\n", $r0, $r7, *(unsigned int*)0x800ed9c
  printf "    Buffer bytes [0..7]: %02x %02x %02x %02x  %02x %02x %02x %02x\n", *(unsigned char*)0x20002792, *(unsigned char*)0x20002793, *(unsigned char*)0x20002794, *(unsigned char*)0x20002795, *(unsigned char*)0x20002796, *(unsigned char*)0x20002797, *(unsigned char*)0x20002798, *(unsigned char*)0x20002799
  printf "    I²C2 ISR: 0x%08x  (bit 4 NACKF, bit 8 TIMEOUT, bit 10 BERR)\n", *(unsigned int*)0x40005818
  continue
end

# Save original PA0 config
set $orig_moder = *(unsigned int*)0x48000000
set $orig_odr   = *(unsigned int*)0x48000014

printf "\n=== Drive PA0 LOW to trigger the handshake ===\n"
set *(unsigned int*)0x48000014 = $orig_odr & ~0x1
set *(unsigned int*)0x48000000 = ($orig_moder & ~0x3) | 0x1

monitor resume
printf "Running for 5s to capture handshake activity...\n"
shell sleep 5
monitor halt

printf "\n=== After 5s ===\n"
printf "I²C2 CR1=0x%08x  ISR=0x%08x\n", *(unsigned int*)0x40005800, *(unsigned int*)0x40005818
printf "Thread state[+8]=0x%02x  state[+9]=0x%02x\n", *(unsigned char*)0x20002618, *(unsigned char*)0x20002619

delete breakpoints

printf "\n=== Restore PA0 ===\n"
set *(unsigned int*)0x48000000 = $orig_moder
set *(unsigned int*)0x48000014 = $orig_odr

monitor resume
quit
