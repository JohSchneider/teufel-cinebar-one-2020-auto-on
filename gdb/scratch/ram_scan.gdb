set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

# Snapshot SRAM at 16-byte chunks, then run for 5s, then re-snapshot.
# Chunks that differ = actively used; chunks unchanged are candidates for our buffer.
set $i = 0
while $i < 256
  set $addr = 0x20000000 + ($i * 64)
  set var $snap[$i*4+0] = *(unsigned int*)($addr+0)
  set var $snap[$i*4+1] = *(unsigned int*)($addr+16)
  set var $snap[$i*4+2] = *(unsigned int*)($addr+32)
  set var $snap[$i*4+3] = *(unsigned int*)($addr+48)
  set $i = $i + 1
end
monitor resume
shell sleep 5
monitor halt

printf "\n=== Changed-region map (64-byte buckets across 16KB SRAM) ===\n"
printf "addr     w0  w16 w32 w48  (X=changed, .=unchanged)\n"
set $i = 0
set $cur_run = 0
while $i < 256
  set $addr = 0x20000000 + ($i * 64)
  set $c0 = (*(unsigned int*)($addr+0)  != $snap[$i*4+0])
  set $c1 = (*(unsigned int*)($addr+16) != $snap[$i*4+1])
  set $c2 = (*(unsigned int*)($addr+32) != $snap[$i*4+2])
  set $c3 = (*(unsigned int*)($addr+48) != $snap[$i*4+3])
  set $changed = $c0 + $c1 + $c2 + $c3
  if $changed > 0
    printf "0x%08X  %d %d %d %d\n", $addr, $c0, $c1, $c2, $c3
  end
  set $i = $i + 1
end
printf "\n(only changed buckets shown; unchanged = candidates for ring buffer)\n"

monitor resume
quit
