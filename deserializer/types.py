from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class ConstantType(IntEnum):
    NIL = 0
    BOOLEAN = 1
    NUMBER = 2
    STRING = 3
    IMPORT = 4
    TABLE = 5
    CLOSURE = 6
    VECTOR = 7


@dataclass
class Constant:
    type: ConstantType
    # Depending on type:
    value_bool: Optional[bool] = None          # BOOLEAN
    value_number: Optional[float] = None       # NUMBER
    value_string_idx: Optional[int] = None     # STRING (index into string table, 1-based; 0 = none)
    value_import: Optional[int] = None         # IMPORT (encoded import id)
    value_table: Optional[list] = None         # TABLE (list of constant indices for keys)
    value_closure: Optional[int] = None        # CLOSURE (proto index)
    value_vector: Optional[tuple] = None       # VECTOR (x, y, z, w)

    def __repr__(self):
        if self.type == ConstantType.NIL:
            return "Constant(nil)"
        elif self.type == ConstantType.BOOLEAN:
            return f"Constant({self.value_bool})"
        elif self.type == ConstantType.NUMBER:
            return f"Constant({self.value_number})"
        elif self.type == ConstantType.STRING:
            return f"Constant(string_idx={self.value_string_idx})"
        elif self.type == ConstantType.IMPORT:
            return f"Constant(import=0x{self.value_import:08X})"
        elif self.type == ConstantType.TABLE:
            return f"Constant(table={self.value_table})"
        elif self.type == ConstantType.CLOSURE:
            return f"Constant(closure={self.value_closure})"
        elif self.type == ConstantType.VECTOR:
            return f"Constant(vector={self.value_vector})"
        return f"Constant(type={self.type})"


@dataclass
class Instruction:
    raw: int             # raw 32-bit instruction word
    opcode: int          # decoded opcode
    a: int = 0           # A field (bits 8-15)
    b: int = 0           # B field (bits 16-23)
    c: int = 0           # C field (bits 24-31)
    d: int = 0           # D field (bits 16-31, signed 16-bit)
    e: int = 0           # E field (bits 8-31, signed 24-bit)
    aux: Optional[int] = None  # auxiliary word (if present)
    pc: int = 0          # program counter (instruction index)

    @staticmethod
    def decode(raw: int, encode_key: int) -> "Instruction":
        encoded_op = raw & 0xFF
        decoded_op = (encoded_op * encode_key) & 0xFF

        a = (raw >> 8) & 0xFF
        b = (raw >> 16) & 0xFF
        c = (raw >> 24) & 0xFF

        # D is signed 16-bit from bits 16-31
        d = raw >> 16
        if d >= 0x8000:
            d -= 0x10000

        # E is signed 24-bit from bits 8-31
        e = raw >> 8
        if e >= 0x800000:
            e -= 0x1000000

        return Instruction(
            raw=raw,
            opcode=decoded_op,
            a=a, b=b, c=c, d=d, e=e
        )


@dataclass
class LocalVar:
    name: str
    start_pc: int
    end_pc: int
    reg: int = 0


@dataclass
class Proto:
    max_stack_size: int = 0
    num_params: int = 0
    num_upvalues: int = 0
    is_vararg: bool = False
    flags: int = 0
    type_info: bytes = b""

    instructions: list = field(default_factory=list)  # list[Instruction]
    constants: list = field(default_factory=list)      # list[Constant]
    child_protos: list = field(default_factory=list)   # list[int] (proto indices)

    line_defined: int = 0
    debug_name_idx: int = 0  # string table index (1-based, 0 = no name)

    line_gap_log2: int = 0
    line_info: list = field(default_factory=list)      # per-instruction line offsets
    abs_line_info: list = field(default_factory=list)   # absolute line numbers

    local_vars: list = field(default_factory=list)     # list[LocalVar]
    upvalue_names: list = field(default_factory=list)   # list[str]


@dataclass
class Chunk:
    version: int = 0
    types_version: int = 0
    string_table: list = field(default_factory=list)   # list[str]
    protos: list = field(default_factory=list)          # list[Proto]
    main_proto: int = 0
