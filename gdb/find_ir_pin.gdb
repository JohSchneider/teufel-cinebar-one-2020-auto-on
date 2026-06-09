# Scan ALL STM32F072 GPIO ports for bits that toggle while the user holds an IR remote.
# Strategy: track per-bit "seen LOW" and "seen HIGH" sets across many samples.
# Any bit seen as BOTH is toggling — likely the IR receiver line.
#
# Usage:
#   1. Hold ANY TV remote button continuously, aimed at the bar's IR window
#   2. While holding, run: gdb-multiarch -batch -x find_ir_pin.gdb
#   3. Output reports any bit that toggled, per port.
#
# Note: PA0/PA1/PA13/PA14 (SWD) and similar reserved pins WILL toggle as part
# of normal operation — focus on bits that toggle correlated with the IR press.
# Compare two runs: one with no remote, one with remote held.

set confirm off
set pagination off
target extended-remote :3333

monitor halt
flushregs

# Accumulators: bits seen LOW (= 0 sometime), bits seen HIGH (= 1 sometime)
set $a_low = 0
set $a_high = 0
set $b_low = 0
set $b_high = 0
set $c_low = 0
set $c_high = 0
set $f_low = 0
set $f_high = 0

set $i = 0
while $i < 800
  # Sample all four ports' IDRs
  set $a = *(unsigned int*)0x48000010 & 0xFFFF
  set $b = *(unsigned int*)0x48000410 & 0xFFFF
  set $c = *(unsigned int*)0x48000810 & 0xFFFF
  set $f = *(unsigned int*)0x48001410 & 0xFFFF

  # Per-bit: a bit is "seen LOW" if it's 0 in this sample;
  #         "seen HIGH" if it's 1 in this sample.
  # OR them across all samples.
  set $a_low  = $a_low  | (~$a & 0xFFFF)
  set $a_high = $a_high | $a
  set $b_low  = $b_low  | (~$b & 0xFFFF)
  set $b_high = $b_high | $b
  set $c_low  = $c_low  | (~$c & 0xFFFF)
  set $c_high = $c_high | $c
  set $f_low  = $f_low  | (~$f & 0xFFFF)
  set $f_high = $f_high | $f
  set $i = $i + 1
end

# A bit "toggled" = seen both LOW and HIGH = low AND high
set $a_toggle = $a_low & $a_high & 0xFFFF
set $b_toggle = $b_low & $b_high & 0xFFFF
set $c_toggle = $c_low & $c_high & 0xFFFF
set $f_toggle = $f_low & $f_high & 0xFFFF

printf "\n=== 800 samples — bits that toggled (= candidate active inputs) ===\n"
printf "GPIOA: toggled bits = 0x%04x\n", $a_toggle
printf "GPIOB: toggled bits = 0x%04x\n", $b_toggle
printf "GPIOC: toggled bits = 0x%04x\n", $c_toggle
printf "GPIOF: toggled bits = 0x%04x\n", $f_toggle

printf "\n=== Bit decode (which pins) ===\n"
set $i = 0
while $i < 16
  if ($a_toggle >> $i) & 1
    printf "  PA%d toggled\n", $i
  end
  if ($b_toggle >> $i) & 1
    printf "  PB%d toggled\n", $i
  end
  if ($c_toggle >> $i) & 1
    printf "  PC%d toggled\n", $i
  end
  if ($f_toggle >> $i) & 1
    printf "  PF%d toggled\n", $i
  end
  set $i = $i + 1
end

monitor resume
detach
quit
