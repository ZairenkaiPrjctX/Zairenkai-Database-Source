"""Minimal, read-only ELF parser for dynamic-linking metadata. Never executes the file.

Reads the ELF header, program headers, and the PT_DYNAMIC segment to obtain DT_NEEDED,
DT_SONAME, DT_RUNPATH/DT_RPATH. String-table virtual addresses are mapped to file offsets via
PT_LOAD segments. All reads are bounds-checked; malformed input raises ElfError.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
MAX_ELF_BYTES = 512 * 1024 * 1024
MACHINES = {3: "x86", 8: "mips", 40: "arm", 62: "x86_64", 183: "aarch64", 243: "riscv"}
TYPES = {1: "relocatable", 2: "executable", 3: "shared_object", 4: "core"}
PT_LOAD, PT_DYNAMIC, PT_INTERP = 1, 2, 3
DT_NULL, DT_NEEDED, DT_STRTAB, DT_STRSZ, DT_SONAME, DT_RPATH, DT_RUNPATH = 0, 1, 5, 10, 14, 15, 29


class ElfError(ValueError):
    pass


@dataclass
class ElfInfo:
    elf_class: str
    endianness: str
    machine: str
    elf_type: str
    interpreter: str | None = None
    soname: str | None = None
    needed: list[str] = field(default_factory=list)
    runpath: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "elf_class": self.elf_class,
            "endianness": self.endianness,
            "machine": self.machine,
            "elf_type": self.elf_type,
            "interpreter": self.interpreter,
            "soname": self.soname,
            "needed": list(self.needed),
            "runpath": list(self.runpath),
        }


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == ELF_MAGIC
    except OSError:
        return False


def parse_file(path: Path) -> ElfInfo:
    size = path.stat().st_size
    if size > MAX_ELF_BYTES:
        raise ElfError(f"ELF larger than {MAX_ELF_BYTES} bytes")
    return parse(path.read_bytes())


def parse(data: bytes) -> ElfInfo:
    if len(data) < 52 or data[:4] != ELF_MAGIC:
        raise ElfError("not an ELF file")
    cls, enc = data[4], data[5]
    if cls not in (1, 2) or enc not in (1, 2):
        raise ElfError("bad ELF class or data encoding")
    is64, end = cls == 2, "<" if enc == 1 else ">"

    def unpack(fmt: str, off: int) -> tuple[int, ...]:
        n = struct.calcsize(end + fmt)
        if off < 0 or off + n > len(data):
            raise ElfError("truncated ELF structure")
        return struct.unpack_from(end + fmt, data, off)

    if is64:
        e_type, e_machine = unpack("HH", 16)
        (e_phoff,) = unpack("Q", 32)
        e_phentsize, e_phnum = unpack("HH", 54)
        ph_fmt, dyn_fmt = "IIQQQQQQ", "qQ"
    else:
        e_type, e_machine = unpack("HH", 16)
        (e_phoff,) = unpack("I", 28)
        e_phentsize, e_phnum = unpack("HH", 42)
        ph_fmt, dyn_fmt = "IIIIIIII", "iI"
    if e_phnum > 4096:
        raise ElfError("unreasonable program header count")

    info = ElfInfo(
        "ELF64" if is64 else "ELF32",
        "little" if enc == 1 else "big",
        MACHINES.get(e_machine, f"unknown({e_machine})"),
        TYPES.get(e_type, f"unknown({e_type})"),
    )

    loads: list[tuple[int, int, int]] = []  # (vaddr, offset, filesz)
    dynamic: tuple[int, int] | None = None
    for i in range(e_phnum):
        f = unpack(ph_fmt, e_phoff + i * e_phentsize)
        if is64:
            p_type, _flags, p_offset, p_vaddr, _pa, p_filesz = f[0], f[1], f[2], f[3], f[4], f[5]
        else:
            p_type, p_offset, p_vaddr, _pa, p_filesz = f[0], f[1], f[2], f[3], f[4]
        if p_type == PT_LOAD:
            loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == PT_DYNAMIC:
            dynamic = (p_offset, p_filesz)
        elif p_type == PT_INTERP and p_offset + p_filesz <= len(data):
            info.interpreter = (
                data[p_offset : p_offset + p_filesz].split(b"\0", 1)[0].decode("utf-8", "replace")
            )
    if dynamic is None:
        return info  # static binary or object: no dynamic dependencies

    entries: list[tuple[int, int]] = []
    step = struct.calcsize(end + dyn_fmt)
    off, stop = dynamic[0], min(dynamic[0] + dynamic[1], len(data))
    while off + step <= stop:
        tag, val = unpack(dyn_fmt, off)
        if tag == DT_NULL:
            break
        entries.append((tag, val))
        off += step

    strtab = next((v for t, v in entries if t == DT_STRTAB), None)
    strsz = next((v for t, v in entries if t == DT_STRSZ), None)
    if strtab is None:
        raise ElfError("PT_DYNAMIC without DT_STRTAB")
    str_off = _vaddr_to_offset(strtab, loads)
    if str_off is None:
        raise ElfError("DT_STRTAB not inside any PT_LOAD segment")
    str_end = min(len(data), str_off + strsz) if strsz else len(data)

    def string(idx: int) -> str:
        start = str_off + idx
        if idx < 0 or start >= str_end:
            raise ElfError("string table index out of range")
        nul = data.find(b"\0", start, str_end)
        return data[start : nul if nul != -1 else str_end].decode("utf-8", "replace")

    for tag, val in entries:
        if tag == DT_NEEDED:
            info.needed.append(string(val))
        elif tag == DT_SONAME:
            info.soname = string(val)
        elif tag in (DT_RUNPATH, DT_RPATH):
            info.runpath.extend(p for p in string(val).split(":") if p)
    return info


def _vaddr_to_offset(vaddr: int, loads: list[tuple[int, int, int]]) -> int | None:
    for seg_vaddr, seg_off, seg_size in loads:
        if seg_vaddr <= vaddr < seg_vaddr + seg_size:
            return seg_off + (vaddr - seg_vaddr)
    return None
