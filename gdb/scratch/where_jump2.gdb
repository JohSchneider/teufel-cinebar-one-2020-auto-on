set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt
delete breakpoints

# Conditional BP at helper entry — only fires when r3 == 12 (cmd_id=12)
break *0x080108E2
condition 1 $r3 == 12
commands
silent
# Read inline table bytes via LR
set $lrv = $lr
set $lim = *(unsigned char*)($lrv - 1)
set $off = *(unsigned char*)($lrv + $r3)
set $target = $lrv + 2*$off
printf "[helper r3=12] LR_v=0x%08X  inline-LIMIT=%d  offset_byte=0x%02X  target=0x%08X\n", $lrv, $lim, $off, ($target & ~1)
continue
end

set $sr0=$r0
set $sr1=$r1
set $sr2=$r2
set $sr3=$r3
set $sr12=$r12
set $slr=$lr
set $spc=$pc
set *(unsigned short*)0x20002000 = 0xBE00
set $r0 = 12
set $r1 = 0x201
set $lr = 0x20002001
set $pc = 0x0800BBDC
continue
printf "notify done, PC=0x%08X\n", $pc

set $r0=$sr0
set $r1=$sr1
set $r2=$sr2
set $r3=$sr3
set $r12=$sr12
set $lr=$slr
set $pc=$spc

monitor resume
shell sleep 2
monitor halt
delete breakpoints
monitor resume
quit
