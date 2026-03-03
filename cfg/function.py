from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set

from .block import BasicBlock

# Import deserializer types
from deserializer.types import Proto, Instruction
from deserializer.opcodes import LuauOpcode, HAS_AUX


# All opcodes that are jump instructions (unconditional or conditional)
UNCONDITIONAL_JUMPS = {
    LuauOpcode.JUMP,
    LuauOpcode.JUMPBACK,
    LuauOpcode.JUMPX,
}

CONDITIONAL_JUMPS = {
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
}

# Loop-related instructions
LOOP_INSTRUCTIONS = {
    LuauOpcode.FORNPREP,
    LuauOpcode.FORNLOOP,
    LuauOpcode.FORGLOOP,
    LuauOpcode.FORGPREP_INEXT,
    LuauOpcode.FORGPREP_NEXT,
    LuauOpcode.FORGPREP,
}

# Instructions that terminate a block (no fall-through)
TERMINATING_INSTRUCTIONS = {
    LuauOpcode.RETURN,
    LuauOpcode.JUMP,
    LuauOpcode.JUMPBACK,
    LuauOpcode.JUMPX,
}

ALL_JUMP_OPCODES = UNCONDITIONAL_JUMPS | CONDITIONAL_JUMPS | LOOP_INSTRUCTIONS


def _get_instruction_pc_step(insn: Instruction) -> int:
    """Get the PC increment for an instruction (accounting for AUX words)."""
    if insn.aux is not None:
        return 2
    return 1


def _compute_jump_target(insn: Instruction) -> Optional[int]:
    """Compute the jump target PC for a jump/branch instruction.

    Luau jumps are relative: target = pc + 1 + D (for AD format)
    or target = pc + 1 + E (for JUMPX with AE format).
    """
    op = insn.opcode
    try:
        opcode = LuauOpcode(op)
    except ValueError:
        return None

    if opcode == LuauOpcode.JUMPX:
        return insn.pc + 1 + insn.e
    elif opcode in (UNCONDITIONAL_JUMPS | CONDITIONAL_JUMPS | LOOP_INSTRUCTIONS):
        return insn.pc + 1 + insn.d
    return None


def _is_block_terminator(insn: Instruction) -> bool:
    """Check if an instruction ends a basic block."""
    try:
        opcode = LuauOpcode(insn.opcode)
    except ValueError:
        return False

    return opcode in (ALL_JUMP_OPCODES | TERMINATING_INSTRUCTIONS)


@dataclass
class FunctionCFG:
    """Control Flow Graph for a single function/proto.

    Contains the set of basic blocks and their control flow edges,
    plus dominator information.
    """
    proto_id: int
    entry_block: Optional[BasicBlock] = None
    blocks: List[BasicBlock] = field(default_factory=list)

    # Maps block_id -> immediate dominator block_id
    dominators: Dict[int, int] = field(default_factory=dict)

    # Lookup: pc -> block containing that pc
    _pc_to_block: Dict[int, BasicBlock] = field(default_factory=dict)

    # Lookup: block_id -> block
    _id_to_block: Dict[int, BasicBlock] = field(default_factory=dict)

    def get_block_by_id(self, block_id: int) -> Optional[BasicBlock]:
        """Look up a block by its ID."""
        return self._id_to_block.get(block_id)

    def get_block_at_pc(self, pc: int) -> Optional[BasicBlock]:
        """Look up the block that contains the given PC."""
        return self._pc_to_block.get(pc)

    @classmethod
    def build(cls, proto: Proto, proto_id: int = 0, encode_key: int = 0) -> 'FunctionCFG':
        """Build a CFG from a proto's instructions.

        Algorithm:
        1. Identify basic block boundaries by scanning for jump targets and
           instructions that follow jumps/branches.
        2. Create BasicBlock objects for each contiguous range.
        3. Add successor/predecessor edges based on fall-through and jump targets.
        """
        instructions = proto.instructions
        if not instructions:
            # Empty function: single empty block
            block = BasicBlock(id=0, start_pc=0, end_pc=0)
            cfg = cls(proto_id=proto_id, entry_block=block, blocks=[block])
            cfg._id_to_block[0] = block
            return cfg

        # Build a map from PC to instruction for fast lookup
        pc_to_insn: Dict[int, Instruction] = {}
        insn_pcs: List[int] = []
        for insn in instructions:
            pc_to_insn[insn.pc] = insn
            insn_pcs.append(insn.pc)

        insn_pcs.sort()

        # Step 1: Find block boundaries
        # A new block starts at:
        #   - PC 0 (function entry)
        #   - The target of any jump
        #   - The instruction immediately after any jump/branch
        block_starts: Set[int] = {0}

        for insn in instructions:
            try:
                opcode = LuauOpcode(insn.opcode)
            except ValueError:
                continue

            # This instruction is a jump/branch
            if opcode in ALL_JUMP_OPCODES or opcode == LuauOpcode.RETURN:
                target = _compute_jump_target(insn)
                if target is not None and target in pc_to_insn:
                    block_starts.add(target)

                # The instruction after this one starts a new block (fall-through)
                step = _get_instruction_pc_step(insn)
                next_pc = insn.pc + step
                if next_pc in pc_to_insn:
                    block_starts.add(next_pc)

            # LOADB with C != 0 skips the next instruction
            if opcode == LuauOpcode.LOADB and insn.c != 0:
                skip_target = insn.pc + 1 + insn.c
                if skip_target in pc_to_insn:
                    block_starts.add(skip_target)
                next_pc = insn.pc + 1
                if next_pc in pc_to_insn:
                    block_starts.add(next_pc)

        # Sort block start PCs
        sorted_starts = sorted(block_starts)

        # Step 2: Create basic blocks
        blocks: List[BasicBlock] = []
        pc_to_block: Dict[int, BasicBlock] = {}
        id_to_block: Dict[int, BasicBlock] = {}

        for idx, start_pc in enumerate(sorted_starts):
            # Find the end PC: just before the next block start, or end of function
            if idx + 1 < len(sorted_starts):
                next_start = sorted_starts[idx + 1]
            else:
                # Last block extends to end of function
                next_start = insn_pcs[-1] + _get_instruction_pc_step(pc_to_insn[insn_pcs[-1]])

            # Collect instructions for this block
            block_insns = []
            end_pc = start_pc
            for pc in insn_pcs:
                if pc >= start_pc and pc < next_start:
                    block_insns.append(pc_to_insn[pc])
                    end_pc = pc

            if not block_insns:
                continue

            block = BasicBlock(
                id=idx,
                start_pc=start_pc,
                end_pc=end_pc,
                instructions=block_insns,
            )
            blocks.append(block)

            # Map each PC in this block to the block
            for insn in block_insns:
                pc_to_block[insn.pc] = block
            id_to_block[block.id] = block

        if not blocks:
            block = BasicBlock(id=0, start_pc=0, end_pc=0)
            cfg = cls(proto_id=proto_id, entry_block=block, blocks=[block])
            cfg._id_to_block[0] = block
            return cfg

        # Step 3: Add control flow edges
        for block in blocks:
            last_insn = block.instructions[-1]
            try:
                opcode = LuauOpcode(last_insn.opcode)
            except ValueError:
                # Unknown opcode: assume fall-through
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)
                continue

            if opcode == LuauOpcode.RETURN:
                # No successors - function returns
                pass

            elif opcode in UNCONDITIONAL_JUMPS:
                # Unconditional jump: single successor at jump target
                target = _compute_jump_target(last_insn)
                if target is not None and target in pc_to_block:
                    target_block = pc_to_block[target]
                    block.add_successor(target_block)

            elif opcode in CONDITIONAL_JUMPS:
                # Conditional jump: two successors
                # 1) Fall-through (condition false)
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)
                # 2) Jump target (condition true)
                target = _compute_jump_target(last_insn)
                if target is not None and target in pc_to_block:
                    target_block = pc_to_block[target]
                    block.add_successor(target_block)

            elif opcode == LuauOpcode.FORNPREP:
                # Numeric for prep: jumps past the loop body if limit already reached,
                # or falls through into the loop body.
                # FORNPREP A D: if init > limit, jump to pc+1+D (past loop); else fall through
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)
                target = _compute_jump_target(last_insn)
                if target is not None and target in pc_to_block:
                    target_block = pc_to_block[target]
                    block.add_successor(target_block)

            elif opcode == LuauOpcode.FORNLOOP:
                # Numeric for loop: jumps back to loop body if iteration continues,
                # or falls through when done.
                # FORNLOOP A D: jump to pc+1+D (back to loop body) if more iterations
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)
                target = _compute_jump_target(last_insn)
                if target is not None and target in pc_to_block:
                    target_block = pc_to_block[target]
                    block.add_successor(target_block)
                    # Mark loop properties
                    target_block.is_loop_header = True
                    block.is_loop_latch = True

            elif opcode in (LuauOpcode.FORGPREP_INEXT, LuauOpcode.FORGPREP_NEXT,
                            LuauOpcode.FORGPREP):
                # Generic for prep: jumps to the FORGLOOP instruction (target),
                # which starts the iteration check.
                # Falls through into the loop body on first iteration,
                # or jumps to target (FORGLOOP) to begin iteration.
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)
                target = _compute_jump_target(last_insn)
                if target is not None and target in pc_to_block:
                    target_block = pc_to_block[target]
                    block.add_successor(target_block)

            elif opcode == LuauOpcode.FORGLOOP:
                # Generic for loop: jumps back to loop body if more iterations,
                # or falls through when done.
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)
                target = _compute_jump_target(last_insn)
                if target is not None and target in pc_to_block:
                    target_block = pc_to_block[target]
                    block.add_successor(target_block)
                    target_block.is_loop_header = True
                    block.is_loop_latch = True

            elif opcode == LuauOpcode.LOADB and last_insn.c != 0:
                # LOADB with skip: jumps over next instruction
                skip_target = last_insn.pc + 1 + last_insn.c
                if skip_target in pc_to_block:
                    block.add_successor(pc_to_block[skip_target])
                # Also add fallthrough for the non-skip case
                # (LOADB C=1 means skip next instruction, so we go to pc+2)
                # Actually LOADB with C!=0 always skips. It's used for boolean
                # short-circuit patterns where the skip is unconditional.
                # But in a block-level view, we just add the skip target.

            else:
                # Default: fall-through to next block
                _add_fallthrough_edge(block, blocks, pc_to_block, insn_pcs, pc_to_insn)

        cfg = cls(
            proto_id=proto_id,
            entry_block=blocks[0],
            blocks=blocks,
            _pc_to_block=pc_to_block,
            _id_to_block=id_to_block,
        )

        # Compute def/use sets for each block
        _compute_block_def_use(cfg)

        return cfg


def _add_fallthrough_edge(
    block: BasicBlock,
    blocks: List[BasicBlock],
    pc_to_block: Dict[int, BasicBlock],
    insn_pcs: List[int],
    pc_to_insn: Dict[int, Instruction],
):
    """Add a fall-through edge from block to the next sequential block."""
    last_insn = block.instructions[-1]
    step = _get_instruction_pc_step(last_insn)
    next_pc = last_insn.pc + step

    if next_pc in pc_to_block:
        next_block = pc_to_block[next_pc]
        if next_block != block:
            block.add_successor(next_block)


def _compute_block_def_use(cfg: 'FunctionCFG'):
    """Compute the set of registers defined and used in each block.

    Uses are registers read before being written in the block.
    Defs are registers written in the block.
    """
    for block in cfg.blocks:
        defs = set()
        uses = set()

        for insn in block.instructions:
            try:
                opcode = LuauOpcode(insn.opcode)
            except ValueError:
                continue

            # Get the registers read and written by this instruction
            reads, writes = _get_insn_reads_writes(insn, opcode)

            # A register is "used" if it's read before being defined in this block
            for reg in reads:
                if reg not in defs:
                    uses.add(reg)

            # Track definitions
            for reg in writes:
                defs.add(reg)

        block.defs = defs
        block.uses = uses


def _get_insn_reads_writes(insn: Instruction, opcode: LuauOpcode):
    """Determine which registers an instruction reads and writes.

    Returns (set of read reg names, set of written reg names).
    Register names are strings like "r0", "r1", etc.
    """
    reads = set()
    writes = set()

    def r(n):
        return f"r{n}"

    # Large switch on opcode categories
    if opcode == LuauOpcode.NOP or opcode == LuauOpcode.BREAK:
        pass

    elif opcode == LuauOpcode.LOADNIL:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.LOADB:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.LOADN:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.LOADK:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.LOADKX:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.MOVE:
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode in (LuauOpcode.GETGLOBAL, LuauOpcode.GETIMPORT):
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.SETGLOBAL:
        reads.add(r(insn.a))

    elif opcode == LuauOpcode.GETUPVAL:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.SETUPVAL:
        reads.add(r(insn.a))

    elif opcode == LuauOpcode.GETTABLE:
        reads.add(r(insn.b))
        reads.add(r(insn.c))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.SETTABLE:
        reads.add(r(insn.a))
        reads.add(r(insn.b))
        reads.add(r(insn.c))

    elif opcode == LuauOpcode.GETTABLEKS:
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.SETTABLEKS:
        reads.add(r(insn.a))
        reads.add(r(insn.b))

    elif opcode == LuauOpcode.GETTABLEN:
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.SETTABLEN:
        reads.add(r(insn.a))
        reads.add(r(insn.b))

    elif opcode in (LuauOpcode.ADD, LuauOpcode.SUB, LuauOpcode.MUL,
                    LuauOpcode.DIV, LuauOpcode.MOD, LuauOpcode.POW,
                    LuauOpcode.IDIV):
        reads.add(r(insn.b))
        reads.add(r(insn.c))
        writes.add(r(insn.a))

    elif opcode in (LuauOpcode.ADDK, LuauOpcode.SUBK, LuauOpcode.MULK,
                    LuauOpcode.DIVK, LuauOpcode.MODK, LuauOpcode.POWK,
                    LuauOpcode.IDIVK, LuauOpcode.SUBRK, LuauOpcode.DIVRK):
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode in (LuauOpcode.AND, LuauOpcode.OR):
        reads.add(r(insn.b))
        reads.add(r(insn.c))
        writes.add(r(insn.a))

    elif opcode in (LuauOpcode.ANDK, LuauOpcode.ORK):
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.CONCAT:
        # CONCAT A B C: concatenate registers B through C, store in A
        for reg_idx in range(insn.b, insn.c + 1):
            reads.add(r(reg_idx))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.NOT:
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.MINUS:
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.LENGTH:
        reads.add(r(insn.b))
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.NEWTABLE:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.DUPTABLE:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.SETLIST:
        reads.add(r(insn.a))
        # Reads registers A+1 through A+B-1
        if insn.b > 0:
            for reg_idx in range(insn.a + 1, insn.a + insn.b):
                reads.add(r(reg_idx))

    elif opcode == LuauOpcode.NEWCLOSURE:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.DUPCLOSURE:
        writes.add(r(insn.a))

    elif opcode == LuauOpcode.NAMECALL:
        reads.add(r(insn.b))
        writes.add(r(insn.a))
        writes.add(r(insn.a + 1))

    elif opcode == LuauOpcode.CALL:
        # CALL A B C: call A with B-1 args (A+1..A+B-1), C-1 results (A..A+C-2)
        reads.add(r(insn.a))
        if insn.b > 0:
            for reg_idx in range(insn.a + 1, insn.a + insn.b - 1):
                reads.add(r(reg_idx))
        if insn.c > 0:
            for reg_idx in range(insn.a, insn.a + insn.c - 1):
                writes.add(r(reg_idx))
        elif insn.c == 0:
            # Variable results, at least writes A
            writes.add(r(insn.a))

    elif opcode == LuauOpcode.RETURN:
        # RETURN A B: return B-1 values starting from A
        if insn.b > 1:
            for reg_idx in range(insn.a, insn.a + insn.b - 1):
                reads.add(r(reg_idx))
        elif insn.b == 0:
            # Return varargs from A upward - conservatively read A
            reads.add(r(insn.a))

    elif opcode in (LuauOpcode.JUMP, LuauOpcode.JUMPBACK, LuauOpcode.JUMPX):
        pass  # No register reads/writes

    elif opcode in (LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT):
        reads.add(r(insn.a))

    elif opcode in (LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
                    LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE,
                    LuauOpcode.JUMPIFNOTLT):
        reads.add(r(insn.a))
        if insn.aux is not None:
            reads.add(r(insn.aux))

    elif opcode in (LuauOpcode.JUMPXEQKNIL, LuauOpcode.JUMPXEQKB,
                    LuauOpcode.JUMPXEQKN, LuauOpcode.JUMPXEQKS):
        reads.add(r(insn.a))

    elif opcode == LuauOpcode.FORNPREP:
        # FORNPREP A D: reads A (init), A+1 (limit), A+2 (step)
        reads.add(r(insn.a))
        reads.add(r(insn.a + 1))
        reads.add(r(insn.a + 2))

    elif opcode == LuauOpcode.FORNLOOP:
        # FORNLOOP A D: reads/writes A (index), A+1 (limit), A+2 (step)
        reads.add(r(insn.a))
        reads.add(r(insn.a + 1))
        reads.add(r(insn.a + 2))
        writes.add(r(insn.a))

    elif opcode in (LuauOpcode.FORGPREP_INEXT, LuauOpcode.FORGPREP_NEXT,
                    LuauOpcode.FORGPREP):
        # Reads iterator state from A, A+1, A+2
        reads.add(r(insn.a))
        reads.add(r(insn.a + 1))
        reads.add(r(insn.a + 2))

    elif opcode == LuauOpcode.FORGLOOP:
        # FORGLOOP A D AUX: reads iterator registers, writes loop variables
        reads.add(r(insn.a))
        reads.add(r(insn.a + 1))
        reads.add(r(insn.a + 2))
        # Number of loop variables is in AUX & 0xff
        if insn.aux is not None:
            num_vars = insn.aux & 0xff
            for i in range(num_vars):
                writes.add(r(insn.a + 3 + i))

    elif opcode == LuauOpcode.GETVARARGS:
        # GETVARARGS A B: write B-1 values starting at A
        if insn.b > 0:
            for reg_idx in range(insn.a, insn.a + insn.b - 1):
                writes.add(r(reg_idx))
        else:
            writes.add(r(insn.a))

    elif opcode == LuauOpcode.PREPVARARGS:
        pass

    elif opcode == LuauOpcode.CLOSEUPVALS:
        pass

    elif opcode == LuauOpcode.CAPTURE:
        # CAPTURE type reg
        if insn.a == 1:  # CAP_VALUE
            reads.add(r(insn.b))
        elif insn.a == 2:  # CAP_REF
            reads.add(r(insn.b))

    elif opcode in (LuauOpcode.FASTCALL, LuauOpcode.FASTCALL1,
                    LuauOpcode.FASTCALL2, LuauOpcode.FASTCALL2K):
        # These are hints that precede a CALL; they don't directly read/write
        # registers in a way we need to track at the block level, since the
        # CALL instruction will handle it.
        pass

    elif opcode == LuauOpcode.COVERAGE:
        pass

    elif opcode == LuauOpcode.NATIVECALL:
        pass

    return reads, writes
