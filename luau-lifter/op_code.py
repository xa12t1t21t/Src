"""Opcode utilities for the Luau bytecode lifter.

Re-exports LuauOpcode from the deserializer and provides lifter-specific
opcode classification helpers.
"""

from deserializer.opcodes import LuauOpcode, HAS_AUX, opcode_name


# Opcodes that perform jumps (have a D or E field used as a jump offset)
JUMP_OPCODES = frozenset({
    LuauOpcode.JUMP,
    LuauOpcode.JUMPBACK,
    LuauOpcode.JUMPIF,
    LuauOpcode.JUMPIFNOT,
    LuauOpcode.JUMPIFEQ,
    LuauOpcode.JUMPIFLE,
    LuauOpcode.JUMPIFLT,
    LuauOpcode.JUMPIFNOTEQ,
    LuauOpcode.JUMPIFNOTLE,
    LuauOpcode.JUMPIFNOTLT,
    LuauOpcode.JUMPXEQKNIL,
    LuauOpcode.JUMPXEQKB,
    LuauOpcode.JUMPXEQKN,
    LuauOpcode.JUMPXEQKS,
})

# Opcodes related to for-loop setup/control
FOR_LOOP_PREP_OPCODES = frozenset({
    LuauOpcode.FORGPREP_NEXT,
    LuauOpcode.FORGPREP_INEXT,
    LuauOpcode.FORGPREP,
})

FOR_LOOP_OPCODES = frozenset({
    LuauOpcode.FORGLOOP,
    LuauOpcode.FORNLOOP,
})

# Opcodes that read from register A (as a source, not destination)
# Used by the pending-expression flush logic
READS_REG_A = frozenset({
    LuauOpcode.SETTABLEKS,
    LuauOpcode.SETTABLE,
    LuauOpcode.SETTABLEN,
    LuauOpcode.SETGLOBAL,
    LuauOpcode.SETUPVAL,
    LuauOpcode.RETURN,
})

# Binary arithmetic opcodes: A = B op C
BINARY_OPS = {
    LuauOpcode.ADD: "+",
    LuauOpcode.SUB: "-",
    LuauOpcode.MUL: "*",
    LuauOpcode.DIV: "/",
    LuauOpcode.MOD: "%",
    LuauOpcode.POW: "^",
    LuauOpcode.IDIV: "//",
}

# Binary arithmetic opcodes with constant: A = B op K[C]
BINARY_K_OPS = {
    LuauOpcode.ADDK: "+",
    LuauOpcode.SUBK: "-",
    LuauOpcode.MULK: "*",
    LuauOpcode.DIVK: "/",
    LuauOpcode.MODK: "%",
    LuauOpcode.POWK: "^",
    LuauOpcode.IDIVK: "//",
}

# Comparison jump opcodes and their then-body (fall-through) operators.
# The then-body runs when the jump is NOT taken, so the operator is the
# negation of the jump condition.
COMPARE_OPS = {
    LuauOpcode.JUMPIFEQ: "~=",       # jump when ==, fall-through when ~=
    LuauOpcode.JUMPIFLE: ">",        # jump when <=, fall-through when >
    LuauOpcode.JUMPIFLT: ">=",       # jump when <, fall-through when >=
    LuauOpcode.JUMPIFNOTEQ: "==",    # jump when ~=, fall-through when ==
    LuauOpcode.JUMPIFNOTLE: "<=",    # jump when >, fall-through when <=
    LuauOpcode.JUMPIFNOTLT: "<",     # jump when >=, fall-through when <
}


def is_jump(opcode: int) -> bool:
    """Check if an opcode is a jump instruction."""
    try:
        return LuauOpcode(opcode) in JUMP_OPCODES
    except ValueError:
        return False


def is_for_prep(opcode: int) -> bool:
    """Check if an opcode is a generic for-loop preparation instruction."""
    try:
        return LuauOpcode(opcode) in FOR_LOOP_PREP_OPCODES
    except ValueError:
        return False
