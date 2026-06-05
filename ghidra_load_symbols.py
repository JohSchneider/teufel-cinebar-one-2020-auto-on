# Ghidra Script — Load Teufel Cinebar One symbols from /tmp/firmware/symbols.csv
#
# Usage:
#   1. In Ghidra, load firmware_01_original-dump.bin as ARM Cortex (little-endian, Thumb),
#      base address 0x08000000, 128 KB.
#      (Apply the STM32F072 SVD via SVD-Loader if you want peripheral labels too.)
#   2. Open Script Manager (Window → Script Manager).
#   3. Create a new Python script (right-click → New → Python).
#   4. Paste the contents of THIS file into the editor.
#   5. Save, then click Run (green arrow).
#
# Script behavior:
#   - Reads /tmp/firmware/symbols.csv from disk.
#   - For each non-comment line, creates a Ghidra Label at the given address
#     with the given name and an end-of-line comment.
#   - For FUNC entries, also creates a function definition at the address.
#   - Idempotent: re-running updates names/comments, doesn't duplicate.
#
# @category Teufel-Cinebar
# @author   (RE notes)

# @runtime PyGhidra

from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import Function
import os
import re

SYMBOLS_FILE = "/tmp/firmware/symbols.csv"

def parse_addr(s):
    s = s.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    return int(s, 16)

def add_symbol(addr_int, name, sym_type, comment):
    """Create / update a label, optionally promote to function. Idempotent."""
    af = currentProgram.getAddressFactory().getDefaultAddressSpace()
    addr = af.getAddress("0x{:x}".format(addr_int))

    # Create or rename label.
    sym_table = currentProgram.getSymbolTable()
    existing = sym_table.getPrimarySymbol(addr)
    if existing is None or existing.getName() != name:
        try:
            sym_table.createLabel(addr, name, SourceType.USER_DEFINED)
        except Exception as e:
            # Fallback: try to set as primary label
            try:
                createLabel(addr, name, True)
            except Exception as e2:
                print("WARN: could not label 0x{:08x} as '{}': {}".format(
                    addr_int, name, e2))
                return

    # For FUNC type, also create a function at this address.
    if sym_type == "FUNC":
        listing = currentProgram.getListing()
        func = listing.getFunctionAt(addr)
        if func is None:
            try:
                # Disassemble first to ensure code is present
                disassemble(addr)
                createFunction(addr, name)
            except Exception as e:
                print("WARN: could not create function at 0x{:08x}: {}".format(
                    addr_int, e))

    # Add EOL comment if provided.
    if comment:
        try:
            setEOLComment(addr, comment)
        except Exception:
            pass

def main():
    if not os.path.exists(SYMBOLS_FILE):
        print("ERROR: {} not found. Adjust SYMBOLS_FILE in the script.".format(
            SYMBOLS_FILE))
        return

    count_func, count_label, count_data, count_skipped = 0, 0, 0, 0

    with open(SYMBOLS_FILE, "r") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            # Split on tabs; require at least 3 fields (addr, name, type)
            parts = line.split("\t")
            if len(parts) < 3:
                print("WARN line {}: too few fields, skipping: {!r}".format(
                    lineno, line))
                count_skipped += 1
                continue
            addr_str, name, sym_type = parts[0], parts[1], parts[2]
            comment = parts[3] if len(parts) >= 4 else ""

            try:
                addr_int = parse_addr(addr_str)
            except ValueError:
                print("WARN line {}: bad address {!r}".format(lineno, addr_str))
                count_skipped += 1
                continue

            add_symbol(addr_int, name.strip(), sym_type.strip(), comment.strip())
            if sym_type.strip() == "FUNC":
                count_func += 1
            elif sym_type.strip() == "DATA":
                count_data += 1
            else:
                count_label += 1

    print("Loaded symbols:")
    print("  functions: {}".format(count_func))
    print("  labels:    {}".format(count_label))
    print("  data:      {}".format(count_data))
    print("  skipped:   {}".format(count_skipped))

main()
