set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Ring header ===\n"
printf "  magic     = 0x%08X  (need 0xC1BAFEED)\n", *(unsigned int*)0x20003E00
printf "  write_idx = %d (byte offset; entry index = idx/8)\n", *(unsigned char*)0x20003E04

printf "\n=== Ring entries (32 entries × 8 bytes) ===\n"
set $i = 0
while $i < 32
  set $addr = 0x20003E10 + $i*8
  set $c = *(unsigned char*)$addr
  set $v = *(unsigned int*)($addr + 4)
  printf "  [%2d @ 0x%08X] cmd_id=%-3d value=0x%08X\n", $i, $addr, $c, $v
  set $i = $i + 1
end

monitor resume
quit
