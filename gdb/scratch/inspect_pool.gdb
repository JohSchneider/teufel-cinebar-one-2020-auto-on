set confirm off
set pagination off
set remotetimeout 60
target extended-remote :3333
monitor halt

printf "\n=== Memory pool descriptor at 0x20000280 ===\n"
printf "(RTX5 osRtxMemoryPool_t: id, state, flags, reserved [4B] + name [4B] + thread_list [4B] +\n"
printf " mp_info {max_blocks, used_blocks, block_size, block_base, block_lim, block_free} [24B])\n"
x/16wx 0x20000280

printf "\n=== Queue descriptor at 0x200000F8 ===\n"
x/16wx 0x200000F8

printf "\n=== Check if the bar's IR receiver might be triggering its own notifies ===\n"
printf "(Watch the pool state for a few seconds — see if anything changes)\n"
monitor resume
shell sleep 3
monitor halt
printf "After 3 sec of running:\n"
x/8wx 0x20000280

monitor resume
quit
