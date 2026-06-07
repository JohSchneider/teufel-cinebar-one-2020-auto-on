set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333

printf "\n>>>>>> FIRE ARDUINO IR-POWER NOW. 15-second window. <<<<<<\n\n"

set $i = 0
set $last_c = 99
set $last_v = 0
while $i < 30
  monitor halt
  set $c = *(unsigned char*)0x20003E00
  set $v = *(unsigned int*)0x20003E04
  if ($c != $last_c) || ($v != $last_v)
    printf "[t+%4.1fs] channel=%-3d value=0x%08X\n", $i*0.5, $c, $v
    set $last_c = $c
    set $last_v = $v
  end
  monitor resume
  shell sleep 0.5
  set $i = $i + 1
end
quit
