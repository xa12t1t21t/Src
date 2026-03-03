"""Pattern matching on CFG structures.

Recognizes common high-level control flow patterns (if/else, while, for)
by examining the shape of the CFG around a given block. These patterns
are used by the restructuring phase to emit proper AST constructs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .block import BasicBlock
from .lib import dominates, get_loop_body
from deserializer.opcodes import LuauOpcode


@dataclass
class IfPattern:
    """Matches an if/else pattern in the CFG.

    Shape:
        condition_block -> then_block -> merge_block
        condition_block -> else_block -> merge_block
    or:
        condition_block -> then_block -> merge_block
        condition_block -> merge_block  (no else)
    """
    condition_block: BasicBlock
    then_block: BasicBlock
    else_block: Optional[BasicBlock]  # None if no else branch
    merge_block: Optional[BasicBlock]  # block where branches reconverge

    # The opcode of the conditional branch
    branch_opcode: Optional[int] = None
    # Whether the condition should be negated
    negate_condition: bool = False


@dataclass
class WhilePattern:
    """Matches a while loop pattern.

    Shape:
        header_block (condition check) -> body_entry -> ... -> latch -> header_block
        header_block -> exit_block
    """
    header: BasicBlock
    body_blocks: List[BasicBlock] = field(default_factory=list)
    latch: BasicBlock = None
    exit_block: Optional[BasicBlock] = None


@dataclass
class RepeatPattern:
    """Matches a repeat-until loop pattern.

    Shape:
        header -> body -> ... -> latch (condition check) -> header (back edge)
        latch -> exit_block
    """
    header: BasicBlock
    body_blocks: List[BasicBlock] = field(default_factory=list)
    latch: BasicBlock = None
    exit_block: Optional[BasicBlock] = None


@dataclass
class ForPattern:
    """Matches a for loop pattern (numeric or generic).

    Numeric for:
        prep_block (FORNPREP) -> body -> ... -> loop_block (FORNLOOP) -> body
        loop_block -> exit_block

    Generic for:
        prep_block (FORGPREP*) -> loop_block (FORGLOOP) -> body -> loop_block
        loop_block -> exit_block
    """
    prep_block: BasicBlock
    loop_block: BasicBlock  # block containing FORNLOOP/FORGLOOP
    body_blocks: List[BasicBlock] = field(default_factory=list)
    exit_block: Optional[BasicBlock] = None
    is_numeric: bool = True
    # For numeric: register base (A operand of FORNPREP)
    register_base: int = 0


def match_if_else(cfg, block: BasicBlock) -> Optional[IfPattern]:
    """Try to match an if/else pattern starting at the given block.

    The block must end with a conditional branch and have exactly two successors.
    """
    if len(block.successors) != 2:
        return None

    if not block.instructions:
        return None

    last_insn = block.instructions[-1]
    try:
        opcode = LuauOpcode(last_insn.opcode)
    except ValueError:
        return None

    # Must be a conditional jump
    conditional_jumps = {
        LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT,
        LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
        LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT,
        LuauOpcode.JUMPXEQKNIL, LuauOpcode.JUMPXEQKB,
        LuauOpcode.JUMPXEQKN, LuauOpcode.JUMPXEQKS,
    }

    if opcode not in conditional_jumps:
        return None

    # Successors: [0] = fall-through, [1] = jump target
    fall_through = block.successors[0]
    jump_target = block.successors[1]

    # Determine if the condition is negated based on opcode
    # JUMPIF jumps when true: then fall-through is "else", jump is "then"
    # JUMPIFNOT jumps when false: fall-through is "then", jump is "else"
    negate = False
    if opcode in (LuauOpcode.JUMPIFNOT, LuauOpcode.JUMPIFNOTEQ,
                  LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT):
        # "NOT" variants: jump target is the "else" path
        then_block = fall_through
        else_block = jump_target
        negate = False
    else:
        # Regular variants: jump target is the "then" path
        then_block = jump_target
        else_block = fall_through
        negate = False

    # Try to find a merge block (where then and else reconverge)
    merge_block = _find_merge_block(then_block, else_block, block)

    # Check for simple if-then (no else): one successor goes directly to merge
    if merge_block is not None:
        if else_block == merge_block:
            # No else body: if cond then ... end
            return IfPattern(
                condition_block=block,
                then_block=then_block,
                else_block=None,
                merge_block=merge_block,
                branch_opcode=opcode,
                negate_condition=negate,
            )

    return IfPattern(
        condition_block=block,
        then_block=then_block,
        else_block=else_block,
        merge_block=merge_block,
        branch_opcode=opcode,
        negate_condition=negate,
    )


def _find_merge_block(
    then_block: BasicBlock,
    else_block: BasicBlock,
    cond_block: BasicBlock,
) -> Optional[BasicBlock]:
    """Find the block where two branches merge back together.

    Looks for a common successor reachable from both branches.
    """
    # Simple case: both branches directly go to the same successor
    then_succs = set(s.id for s in then_block.successors)
    else_succs = set(s.id for s in else_block.successors)
    common = then_succs & else_succs

    if common:
        # Return the common successor with smallest id (closest merge point)
        for succ in then_block.successors:
            if succ.id in common:
                return succ

    # Check if then_block falls through to else_block's successor
    # (meaning the else_block IS the merge)
    if else_block in then_block.successors:
        return else_block

    # Check if then_block's successor == else_block (no else case)
    if then_block in else_block.successors:
        return then_block

    # BFS from both sides to find first common reachable block (limited depth)
    then_reachable = _bfs_reachable(then_block, max_depth=8)
    else_reachable = _bfs_reachable(else_block, max_depth=8)
    common_reachable = then_reachable & else_reachable

    # Exclude the condition block and the branches themselves from merge candidates
    common_reachable -= {cond_block.id, then_block.id, else_block.id}

    if common_reachable:
        return None  # We found common reachable blocks but can't determine which is the merge

    return None


def _bfs_reachable(start: BasicBlock, max_depth: int = 10) -> set:
    """BFS to find reachable block IDs within a depth limit."""
    visited = set()
    frontier = [(start, 0)]

    while frontier:
        block, depth = frontier.pop(0)
        if block.id in visited or depth > max_depth:
            continue
        visited.add(block.id)
        for succ in block.successors:
            frontier.append((succ, depth + 1))

    return visited


def match_while_loop(cfg, block: BasicBlock) -> Optional[WhilePattern]:
    """Try to match a while loop pattern at the given block.

    A while loop has a header that checks a condition, a body, and a back edge
    from the latch to the header. The header must be a loop header that
    ends with a conditional branch.
    """
    if not block.is_loop_header:
        return None

    if not block.instructions:
        return None

    # The header should end with a conditional branch
    last_insn = block.instructions[-1]
    try:
        opcode = LuauOpcode(last_insn.opcode)
    except ValueError:
        return None

    # Skip for-loop patterns (they use FORNLOOP/FORGLOOP)
    if opcode in (LuauOpcode.FORNLOOP, LuauOpcode.FORGLOOP,
                  LuauOpcode.FORNPREP, LuauOpcode.FORGPREP,
                  LuauOpcode.FORGPREP_INEXT, LuauOpcode.FORGPREP_NEXT):
        return None

    # Find the latch (predecessor with a back edge to this header)
    latch = None
    for pred in block.predecessors:
        if pred.is_loop_latch:
            latch = pred
            break

    if latch is None:
        # Try to find a back edge from any predecessor
        for pred in block.predecessors:
            # A predecessor that comes after the header in program order
            if pred.start_pc > block.start_pc:
                latch = pred
                break

    if latch is None:
        return None

    # Get loop body blocks
    body = get_loop_body(cfg, block, latch)

    # Find the exit block (successor of header that's not in the loop body)
    exit_block = None
    body_ids = {b.id for b in body}
    for succ in block.successors:
        if succ.id not in body_ids:
            exit_block = succ
            break

    return WhilePattern(
        header=block,
        body_blocks=body,
        latch=latch,
        exit_block=exit_block,
    )


def match_repeat_until(cfg, block: BasicBlock) -> Optional[RepeatPattern]:
    """Try to match a repeat-until loop pattern.

    In a repeat-until loop, the condition is checked at the end (the latch),
    rather than at the header. The header is just the loop entry.
    """
    if not block.is_loop_header:
        return None

    # Find the latch
    latch = None
    for pred in block.predecessors:
        if pred.is_loop_latch and pred.start_pc > block.start_pc:
            latch = pred
            break

    if latch is None:
        return None

    # The latch should end with a conditional branch (the until condition)
    if not latch.instructions:
        return None

    last_insn = latch.instructions[-1]
    try:
        opcode = LuauOpcode(last_insn.opcode)
    except ValueError:
        return None

    # The latch must have a conditional branch, and the header should NOT
    # have a conditional branch (distinguishes from while loops)
    conditional_jumps = {
        LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT,
        LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
        LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT,
    }

    if opcode not in conditional_jumps:
        return None

    # Check that the header does NOT end with a conditional jump (that would be while)
    if block.instructions:
        header_last = block.instructions[-1]
        try:
            header_op = LuauOpcode(header_last.opcode)
            if header_op in conditional_jumps:
                return None  # This is a while loop, not repeat-until
        except ValueError:
            pass

    body = get_loop_body(cfg, block, latch)
    body_ids = {b.id for b in body}

    # Find exit block
    exit_block = None
    for succ in latch.successors:
        if succ.id not in body_ids:
            exit_block = succ
            break

    return RepeatPattern(
        header=block,
        body_blocks=body,
        latch=latch,
        exit_block=exit_block,
    )


def match_for_loop(cfg, block: BasicBlock) -> Optional[ForPattern]:
    """Try to match a for loop pattern (numeric or generic) at the given block.

    Numeric for loops use FORNPREP/FORNLOOP.
    Generic for loops use FORGPREP*/FORGLOOP.
    """
    if not block.instructions:
        return None

    last_insn = block.instructions[-1]
    try:
        opcode = LuauOpcode(last_insn.opcode)
    except ValueError:
        return None

    # Match numeric for: look for FORNPREP
    if opcode == LuauOpcode.FORNPREP:
        return _match_numeric_for(cfg, block, last_insn)

    # Match generic for: look for FORGPREP variants
    if opcode in (LuauOpcode.FORGPREP, LuauOpcode.FORGPREP_INEXT,
                  LuauOpcode.FORGPREP_NEXT):
        return _match_generic_for(cfg, block, last_insn)

    return None


def _match_numeric_for(cfg, prep_block: BasicBlock, prep_insn) -> Optional[ForPattern]:
    """Match a numeric for loop starting with FORNPREP."""
    target_pc = prep_insn.pc + 1 + prep_insn.d

    # Find the FORNLOOP block
    loop_block = None
    for block in cfg.blocks:
        for insn in block.instructions:
            try:
                if LuauOpcode(insn.opcode) == LuauOpcode.FORNLOOP and insn.pc == target_pc:
                    loop_block = block
                    break
            except ValueError:
                continue
        if loop_block is not None:
            break

    # If we didn't find the exact PC, try finding the block at that PC
    if loop_block is None:
        loop_block = cfg.get_block_at_pc(target_pc) if hasattr(cfg, 'get_block_at_pc') else None

    if loop_block is None:
        return None

    # Collect body blocks between prep and loop
    body_blocks = []
    body_ids = set()
    for block in cfg.blocks:
        if (block.start_pc > prep_block.start_pc and
                block.start_pc <= loop_block.start_pc):
            body_blocks.append(block)
            body_ids.add(block.id)

    # Find exit block
    exit_block = None
    for succ in loop_block.successors:
        if succ.id not in body_ids and succ != prep_block:
            exit_block = succ
            break

    # Also check: FORNPREP can jump to exit when loop is empty
    for succ in prep_block.successors:
        if succ.id not in body_ids and succ != prep_block:
            # This might be the exit when skipping the loop
            if exit_block is None:
                exit_block = succ

    return ForPattern(
        prep_block=prep_block,
        loop_block=loop_block,
        body_blocks=body_blocks,
        exit_block=exit_block,
        is_numeric=True,
        register_base=prep_insn.a,
    )


def _match_generic_for(cfg, prep_block: BasicBlock, prep_insn) -> Optional[ForPattern]:
    """Match a generic for loop starting with FORGPREP*."""
    target_pc = prep_insn.pc + 1 + prep_insn.d

    # Find the FORGLOOP block
    loop_block = None
    for block in cfg.blocks:
        for insn in block.instructions:
            try:
                if LuauOpcode(insn.opcode) == LuauOpcode.FORGLOOP and insn.pc == target_pc:
                    loop_block = block
                    break
            except ValueError:
                continue
        if loop_block is not None:
            break

    if loop_block is None:
        loop_block = cfg.get_block_at_pc(target_pc) if hasattr(cfg, 'get_block_at_pc') else None

    if loop_block is None:
        return None

    # Collect body blocks
    body_blocks = []
    body_ids = set()
    for block in cfg.blocks:
        if (block.start_pc > prep_block.start_pc and
                block.start_pc <= loop_block.start_pc):
            body_blocks.append(block)
            body_ids.add(block.id)

    # Find exit block
    exit_block = None
    for succ in loop_block.successors:
        if succ.id not in body_ids and succ != prep_block:
            exit_block = succ
            break

    return ForPattern(
        prep_block=prep_block,
        loop_block=loop_block,
        body_blocks=body_blocks,
        exit_block=exit_block,
        is_numeric=False,
        register_base=prep_insn.a,
    )


def match_all_patterns(cfg) -> dict:
    """Scan the entire CFG and collect all recognized patterns.

    Returns a dict with keys 'if_patterns', 'while_patterns', 'for_patterns',
    'repeat_patterns', each mapping to a list of matched patterns.
    """
    result = {
        'if_patterns': [],
        'while_patterns': [],
        'for_patterns': [],
        'repeat_patterns': [],
    }

    matched_blocks = set()

    # First pass: match for loops (most specific)
    for block in cfg.blocks:
        pat = match_for_loop(cfg, block)
        if pat is not None:
            result['for_patterns'].append(pat)
            matched_blocks.add(block.id)

    # Second pass: match while and repeat loops
    for block in cfg.blocks:
        if block.id in matched_blocks:
            continue

        pat = match_repeat_until(cfg, block)
        if pat is not None:
            result['repeat_patterns'].append(pat)
            matched_blocks.add(block.id)
            continue

        pat = match_while_loop(cfg, block)
        if pat is not None:
            result['while_patterns'].append(pat)
            matched_blocks.add(block.id)

    # Third pass: match if/else
    for block in cfg.blocks:
        if block.id in matched_blocks:
            continue

        pat = match_if_else(cfg, block)
        if pat is not None:
            result['if_patterns'].append(pat)
            matched_blocks.add(block.id)

    return result
