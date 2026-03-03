from enum import IntEnum


class LuauOpcode(IntEnum):
    NOP = 0
    BREAK = 1
    LOADNIL = 2
    LOADB = 3
    LOADN = 4
    LOADK = 5
    MOVE = 6
    GETGLOBAL = 7
    SETGLOBAL = 8
    GETUPVAL = 9
    SETUPVAL = 10
    CLOSEUPVALS = 11
    GETIMPORT = 12
    GETTABLE = 13
    SETTABLE = 14
    GETTABLEKS = 15
    SETTABLEKS = 16
    GETTABLEN = 17
    SETTABLEN = 18
    NEWCLOSURE = 19
    NAMECALL = 20
    CALL = 21
    RETURN = 22
    JUMP = 23
    JUMPBACK = 24
    JUMPIF = 25
    JUMPIFNOT = 26
    JUMPIFEQ = 27
    JUMPIFLE = 28
    JUMPIFLT = 29
    JUMPIFNOTEQ = 30
    JUMPIFNOTLE = 31
    JUMPIFNOTLT = 32
    ADD = 33
    SUB = 34
    MUL = 35
    DIV = 36
    MOD = 37
    POW = 38
    ADDK = 39
    SUBK = 40
    MULK = 41
    DIVK = 42
    MODK = 43
    POWK = 44
    AND = 45
    OR = 46
    ANDK = 47
    ORK = 48
    CONCAT = 49
    NOT = 50
    MINUS = 51
    LENGTH = 52
    NEWTABLE = 53
    DUPTABLE = 54
    SETLIST = 55
    FORNPREP = 56
    FORNLOOP = 57
    FORGLOOP = 58
    FORGPREP_INEXT = 59
    DEP_FORGLOOP_INEXT = 60
    FORGPREP_NEXT = 61
    NATIVECALL = 62
    GETVARARGS = 63
    DUPCLOSURE = 64
    PREPVARARGS = 65
    LOADKX = 66
    JUMPX = 67
    FASTCALL = 68
    COVERAGE = 69
    CAPTURE = 70
    SUBRK = 71
    DIVRK = 72
    FASTCALL1 = 73
    FASTCALL2 = 74
    FASTCALL2K = 75
    FORGPREP = 76
    JUMPXEQKNIL = 77
    JUMPXEQKB = 78
    JUMPXEQKN = 79
    JUMPXEQKS = 80
    IDIV = 81
    IDIVK = 82


# Instruction format types
class InsnFormat:
    NONE = "NONE"   # no operands (NOP, BREAK)
    AB = "AB"       # A, B (8-bit each), C unused
    ABC = "ABC"     # A, B, C (8-bit each)
    AD = "AD"       # A (8-bit), D (signed 16-bit)
    AE = "AE"       # A (8-bit), E (signed 24-bit)


# Which opcodes consume an AUX word after them
HAS_AUX = {
    LuauOpcode.GETGLOBAL,
    LuauOpcode.SETGLOBAL,
    LuauOpcode.GETIMPORT,
    LuauOpcode.GETTABLEKS,
    LuauOpcode.SETTABLEKS,
    LuauOpcode.NAMECALL,
    LuauOpcode.JUMPIFEQ,
    LuauOpcode.JUMPIFLE,
    LuauOpcode.JUMPIFLT,
    LuauOpcode.JUMPIFNOTEQ,
    LuauOpcode.JUMPIFNOTLE,
    LuauOpcode.JUMPIFNOTLT,
    LuauOpcode.NEWTABLE,
    LuauOpcode.SETLIST,
    LuauOpcode.FORGLOOP,
    LuauOpcode.LOADKX,
    LuauOpcode.FASTCALL2,
    LuauOpcode.FASTCALL2K,
    LuauOpcode.JUMPXEQKNIL,
    LuauOpcode.JUMPXEQKB,
    LuauOpcode.JUMPXEQKN,
    LuauOpcode.JUMPXEQKS,
}

# Instruction format per opcode
OPCODE_FORMAT = {
    LuauOpcode.NOP: InsnFormat.NONE,
    LuauOpcode.BREAK: InsnFormat.NONE,
    LuauOpcode.LOADNIL: InsnFormat.AD,       # A
    LuauOpcode.LOADB: InsnFormat.ABC,        # A B C
    LuauOpcode.LOADN: InsnFormat.AD,         # A D
    LuauOpcode.LOADK: InsnFormat.AD,         # A D
    LuauOpcode.MOVE: InsnFormat.AB,          # A B
    LuauOpcode.GETGLOBAL: InsnFormat.AD,     # A AUX
    LuauOpcode.SETGLOBAL: InsnFormat.AD,     # A AUX
    LuauOpcode.GETUPVAL: InsnFormat.AB,      # A B
    LuauOpcode.SETUPVAL: InsnFormat.AB,      # A B
    LuauOpcode.CLOSEUPVALS: InsnFormat.AD,   # A
    LuauOpcode.GETIMPORT: InsnFormat.AD,     # A D AUX
    LuauOpcode.GETTABLE: InsnFormat.ABC,     # A B C
    LuauOpcode.SETTABLE: InsnFormat.ABC,     # A B C
    LuauOpcode.GETTABLEKS: InsnFormat.ABC,   # A B AUX
    LuauOpcode.SETTABLEKS: InsnFormat.ABC,   # A B AUX
    LuauOpcode.GETTABLEN: InsnFormat.ABC,    # A B C
    LuauOpcode.SETTABLEN: InsnFormat.ABC,    # A B C
    LuauOpcode.NEWCLOSURE: InsnFormat.AD,    # A D
    LuauOpcode.NAMECALL: InsnFormat.ABC,     # A B AUX
    LuauOpcode.CALL: InsnFormat.ABC,         # A B C
    LuauOpcode.RETURN: InsnFormat.AB,        # A B
    LuauOpcode.JUMP: InsnFormat.AD,          # D
    LuauOpcode.JUMPBACK: InsnFormat.AD,      # D
    LuauOpcode.JUMPIF: InsnFormat.AD,        # A D
    LuauOpcode.JUMPIFNOT: InsnFormat.AD,     # A D
    LuauOpcode.JUMPIFEQ: InsnFormat.AD,      # A D AUX
    LuauOpcode.JUMPIFLE: InsnFormat.AD,      # A D AUX
    LuauOpcode.JUMPIFLT: InsnFormat.AD,      # A D AUX
    LuauOpcode.JUMPIFNOTEQ: InsnFormat.AD,   # A D AUX
    LuauOpcode.JUMPIFNOTLE: InsnFormat.AD,   # A D AUX
    LuauOpcode.JUMPIFNOTLT: InsnFormat.AD,   # A D AUX
    LuauOpcode.ADD: InsnFormat.ABC,
    LuauOpcode.SUB: InsnFormat.ABC,
    LuauOpcode.MUL: InsnFormat.ABC,
    LuauOpcode.DIV: InsnFormat.ABC,
    LuauOpcode.MOD: InsnFormat.ABC,
    LuauOpcode.POW: InsnFormat.ABC,
    LuauOpcode.ADDK: InsnFormat.ABC,
    LuauOpcode.SUBK: InsnFormat.ABC,
    LuauOpcode.MULK: InsnFormat.ABC,
    LuauOpcode.DIVK: InsnFormat.ABC,
    LuauOpcode.MODK: InsnFormat.ABC,
    LuauOpcode.POWK: InsnFormat.ABC,
    LuauOpcode.AND: InsnFormat.ABC,
    LuauOpcode.OR: InsnFormat.ABC,
    LuauOpcode.ANDK: InsnFormat.ABC,
    LuauOpcode.ORK: InsnFormat.ABC,
    LuauOpcode.CONCAT: InsnFormat.ABC,       # A B C
    LuauOpcode.NOT: InsnFormat.AB,           # A B
    LuauOpcode.MINUS: InsnFormat.AB,         # A B
    LuauOpcode.LENGTH: InsnFormat.AB,        # A B
    LuauOpcode.NEWTABLE: InsnFormat.AB,      # A B AUX
    LuauOpcode.DUPTABLE: InsnFormat.AD,      # A D
    LuauOpcode.SETLIST: InsnFormat.ABC,      # A B C AUX
    LuauOpcode.FORNPREP: InsnFormat.AD,      # A D
    LuauOpcode.FORNLOOP: InsnFormat.AD,      # A D
    LuauOpcode.FORGLOOP: InsnFormat.AD,      # A D AUX
    LuauOpcode.FORGPREP_INEXT: InsnFormat.AD,
    LuauOpcode.DEP_FORGLOOP_INEXT: InsnFormat.AD,
    LuauOpcode.FORGPREP_NEXT: InsnFormat.AD,
    LuauOpcode.NATIVECALL: InsnFormat.ABC,
    LuauOpcode.GETVARARGS: InsnFormat.AB,    # A B
    LuauOpcode.DUPCLOSURE: InsnFormat.AD,    # A D
    LuauOpcode.PREPVARARGS: InsnFormat.AD,   # A
    LuauOpcode.LOADKX: InsnFormat.AD,        # A AUX
    LuauOpcode.JUMPX: InsnFormat.AE,         # E
    LuauOpcode.FASTCALL: InsnFormat.ABC,     # A C
    LuauOpcode.COVERAGE: InsnFormat.AE,
    LuauOpcode.CAPTURE: InsnFormat.AB,       # A B
    LuauOpcode.SUBRK: InsnFormat.ABC,
    LuauOpcode.DIVRK: InsnFormat.ABC,
    LuauOpcode.FASTCALL1: InsnFormat.ABC,    # A B C
    LuauOpcode.FASTCALL2: InsnFormat.ABC,    # A B C AUX
    LuauOpcode.FASTCALL2K: InsnFormat.ABC,   # A B C AUX
    LuauOpcode.FORGPREP: InsnFormat.AD,      # A D
    LuauOpcode.JUMPXEQKNIL: InsnFormat.AD,   # A D AUX
    LuauOpcode.JUMPXEQKB: InsnFormat.AD,     # A D AUX
    LuauOpcode.JUMPXEQKN: InsnFormat.AD,     # A D AUX
    LuauOpcode.JUMPXEQKS: InsnFormat.AD,     # A D AUX
    LuauOpcode.IDIV: InsnFormat.ABC,
    LuauOpcode.IDIVK: InsnFormat.ABC,
}


def opcode_name(op: int) -> str:
    try:
        return LuauOpcode(op).name
    except ValueError:
        return f"UNKNOWN_{op}"
