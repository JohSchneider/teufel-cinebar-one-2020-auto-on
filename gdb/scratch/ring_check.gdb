set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Bar state ===\n"
printf "  PC = 0x%08X  state[0] = %d\n", $pc, *(unsigned char*)0x200025DC
printf "  notify@0x0800BBDC = 0x%04X 0x%04X (need 0xf012 0xbe60 = b.w trampoline)\n", *(unsigned short*)0x0800BBDC, *(unsigned short*)0x0800BBDE

printf "\n=== Ring buffer header at 0x20003E00 ===\n"
printf "  magic     = 0x%08X  (need 0xC1BAFEED)\n", *(unsigned int*)0x20003E00
printf "  write_idx = %d\n", *(unsigned int*)0x20003E04
printf "  count     = %d\n", *(unsigned int*)0x20003E08

printf "\n=== Ring entries (up to first 16) ===\n"
set $i = 0
while $i < 16
  set $addr = 0x20003E10 + $i*8
  set $cmd = *(unsigned char*)$addr
  set $val = *(unsigned int*)($addr+4)
  if ($cmd != 0) || ($val != 0)
    printf "  [%2d] cmd=%3d value=0x%08X\n", $i, $cmd, $val
  end
  set $i = $i + 1
end

monitor resume
quit
