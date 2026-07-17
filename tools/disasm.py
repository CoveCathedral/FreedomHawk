"""Disassemble a named function from the x86 build of libAmplifiRemoteNdk.so."""
import sys
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PATH = "extracted/lib/x86/libAmplifiRemoteNdk.so"

def load():
    f = ELFFile(open(PATH, "rb"))
    syms = {}
    for secname in (".symtab", ".dynsym"):
        sec = f.get_section_by_name(secname)
        if not sec: continue
        for s in sec.iter_symbols():
            if s['st_value'] and s.name:
                syms.setdefault(s.name, (s['st_value'], s['st_size']))
    return f, syms

def vaddr_to_off(f, vaddr):
    for sec in f.iter_sections():
        a, sz = sec['sh_addr'], sec['sh_size']
        if a and a <= vaddr < a + sz and sec['sh_type'] != 'SHT_NOBITS':
            return sec['sh_offset'] + (vaddr - a)
    return None

def disasm(name, extra=0):
    f, syms = load()
    if name not in syms:
        print(f"!! {name} not found"); return
    va, size = syms[name]
    size = (size or 64) + extra
    off = vaddr_to_off(f, va)
    f.stream.seek(off)
    code = f.stream.read(size)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    print(f"=== {name}  va=0x{va:x} size={size} ===")
    for ins in md.disasm(code, va):
        print(f"  0x{ins.address:x}:  {ins.mnemonic:<7} {ins.op_str}")

if __name__ == "__main__":
    for a in sys.argv[1:]:
        name, _, extra = a.partition("+")
        disasm(name, int(extra or 0)); print()
