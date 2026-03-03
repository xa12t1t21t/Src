"""Instruction utilities for the Luau bytecode lifter.

Provides helper functions that operate on deserializer Instruction objects,
adding lifter-specific computations like jump target resolution.
"""

from deserializer.types import Instruction
from deserializer.opcodes import LuauOpcode
from .op_code import JUMP_OPCODES, FOR_LOOP_PREP_OPCODES, FOR_LOOP_OPCODES


def get_jump_target(insn: Instruction) -> int:
    """Compute the absolute PC target of a jump or for-loop instruction.

    For jump/for-prep instructions, the target is: insn.pc + insn.d + 1
    The +1 accounts for the fact that jumps are relative to the next instruction.

    Args:
        insn: The instruction with a D field jump offset.

    Returns:
        The absolute PC (instruction index in the raw stream) that the jump targets.
    """
    return insn.pc + insn.d + 1


def is_jump(insn: Instruction) -> bool:
    """Check if an instruction is a jump (conditional or unconditional).

    Args:
        insn: The instruction to check.

    Returns:
        True if the instruction is a jump opcode.
    """
    try:
        return LuauOpcode(insn.opcode) in JUMP_OPCODES
    except ValueError:
        return False


def is_for_prep(insn: Instruction) -> bool:
    """Check if an instruction is a generic for-loop prep.

    Args:
        insn: The instruction to check.

    Returns:
        True if the instruction is FORGPREP_NEXT, FORGPREP_INEXT, or FORGPREP.
    """
    try:
        return LuauOpcode(insn.opcode) in FOR_LOOP_PREP_OPCODES
    except ValueError:
        return False


def is_for_loop(insn: Instruction) -> bool:
    """Check if an instruction is a for-loop back edge (FORGLOOP or FORNLOOP).

    Args:
        insn: The instruction to check.

    Returns:
        True if the instruction is FORGLOOP or FORNLOOP.
    """
    try:
        return LuauOpcode(insn.opcode) in FOR_LOOP_OPCODES
    except ValueError:
        return False


def reads_register(insn: Instruction, reg: int) -> bool:
    """Check if an instruction reads from a given register.

    This is a conservative approximation used by the pending-expression
    flush logic. It checks common patterns where a register is used as
    a source operand.

    Args:
        insn: The instruction to check.
        reg: The register number to look for.

    Returns:
        True if the instruction likely reads from the given register.
    """
    op = insn.opcode
    try:
        luau_op = LuauOpcode(op)
    except ValueError:
        return False

    # MOVE A, B -- reads B
    if luau_op == LuauOpcode.MOVE:
        return insn.b == reg

    # SETTABLEKS A, B, AUX -- reads A (value) and B (table)
    if luau_op == LuauOpcode.SETTABLEKS:
        return insn.a == reg or insn.b == reg

    # SETTABLE A, B, C -- reads A (value), B (table), C (key)
    if luau_op == LuauOpcode.SETTABLE:
        return insn.a == reg or insn.b == reg or insn.c == reg

    # CALL A, B, C -- reads A (func) and A+1..A+nargs
    if luau_op == LuauOpcode.CALL:
        nargs = insn.b - 1 if insn.b > 0 else 0
        if reg == insn.a:
            return True
        if insn.b > 0 and insn.a + 1 <= reg <= insn.a + nargs:
            return True
        return False

    # RETURN A, B -- reads A..A+B-2
    if luau_op == LuauOpcode.RETURN:
        if insn.b > 1:
            return insn.a <= reg <= insn.a + insn.b - 2
        return False

    # GETTABLEKS A, B, AUX -- reads B
    if luau_op == LuauOpcode.GETTABLEKS:
        return insn.b == reg

    # GETTABLE A, B, C -- reads B and C
    if luau_op == LuauOpcode.GETTABLE:
        return insn.b == reg or insn.c == reg

    # Binary ops: ADD/SUB/etc A, B, C -- reads B, C
    if luau_op in (LuauOpcode.ADD, LuauOpcode.SUB, LuauOpcode.MUL,
                   LuauOpcode.DIV, LuauOpcode.MOD, LuauOpcode.POW,
                   LuauOpcode.IDIV):
        return insn.b == reg or insn.c == reg

    # CONCAT A, B, C -- reads B..C
    if luau_op == LuauOpcode.CONCAT:
        return insn.b <= reg <= insn.c

    # Unary ops: NOT, MINUS, LENGTH -- reads B
    if luau_op in (LuauOpcode.NOT, LuauOpcode.MINUS, LuauOpcode.LENGTH):
        return insn.b == reg

    # SETGLOBAL A -- reads A
    if luau_op == LuauOpcode.SETGLOBAL:
        return insn.a == reg

    # SETUPVAL A, B -- reads A
    if luau_op == LuauOpcode.SETUPVAL:
        return insn.a == reg

    # FORGPREP_NEXT/FORGPREP_INEXT/FORGPREP -- reads A, A+1, A+2
    if luau_op in (LuauOpcode.FORGPREP_NEXT, LuauOpcode.FORGPREP_INEXT,
                   LuauOpcode.FORGPREP):
        return insn.a <= reg <= insn.a + 2

    # JUMPIF/JUMPIFNOT -- reads A
    if luau_op in (LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT):
        return insn.a == reg

    # Comparison jumps -- reads A and AUX
    if luau_op in (LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE,
                   LuauOpcode.JUMPIFLT, LuauOpcode.JUMPIFNOTEQ,
                   LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT):
        return insn.a == reg or (insn.aux is not None and insn.aux == reg)

    # SETLIST A, B, C, AUX -- reads A (table) and B..B+C-1
    if luau_op == LuauOpcode.SETLIST:
        if insn.a == reg:
            return True
        count = insn.c - 1 if insn.c > 0 else 0
        return insn.b <= reg <= insn.b + count

    # CAPTURE -- reads B
    if luau_op == LuauOpcode.CAPTURE:
        return insn.b == reg

    return False
