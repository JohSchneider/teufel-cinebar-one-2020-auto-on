set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333

printf "\n>>>>>> Fire IR at: 3s, 8s, 13s.  Watch the log slot. <<<<<<\n\n"

set $i = 0
while $i < 40
  monitor halt
  set $c = *(unsigned char*)0x20003E00
  set $v = *(unsigned int*)0x20003E04
  if (($c != 9) || ($v != 9)) && (($c != 14) || ($v != 3))
    printf "[t+%4.1fs] ★ channel=%-3d value=0x%08X  (non-heartbeat!)\n", $i*0.5, $c, $v
  end
  monitor resume
  shell sleep 0.5
  set $i = $i + 1
end
printf "\nDone.\n"
quit
