set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333

set $i = 0
while $i < 6
  monitor halt
  printf "[t+%ds] channel=%-3d  value=0x%08X\n", $i*2, *(unsigned char*)0x20003E00, *(unsigned int*)0x20003E04
  monitor resume
  shell sleep 2
  set $i = $i + 1
end

quit
