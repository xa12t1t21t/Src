"""Loop restructuring pass.

Identifies and restructures loops in the CFG. Handles:
- While loops: condition at the header
- Repeat-until loops: condition at the latch
- Numeric for loops: FORNPREP/FORNLOOP pair
- Generic for loops: FORGPREP*/FORGLOOP pair

The restructuring annotates blocks with loop membership information
and ensures the CFG is properly structured for the AST emission phase.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from cfg.src.lib import (
    find_loops, get_loop_body, compute_dominators,
    compute_loop_depths, dominates,
)
from cfg.src.pattern import (
    match_for_loop, match_while_loop, match_repeat_until,
    ForPattern, WhilePattern, RepeatPattern,
)

from deserializer.opcodes import LuauOpcode

if TYPE_CHECKING:
    from cfg.src.function import FunctionCFG
    from cfg.src.block import BasicBlock


class LoopInfo:
    """Information about a restructured loop."""

    def __init__(
        self,
        header: 'BasicBlock',
        latch: 'BasicBlock',
        body_blocks: List['BasicBlock'],
        exit_block: Optional['BasicBlock'],
        loop_type: str,  # "while", "repeat", "numeric_for", "generic_for"
    ):
        self.header = header
        self.latch = latch
        self.body_blocks = body_blocks
        self.exit_block = exit_block
        self.loop_type = loop_type
        self.nesting_depth = 0
        self.parent_loop: Optional[LoopInfo] = None
        self.child_loops: List[LoopInfo] = []

    @property
    def body_block_ids(self) -> Set[int]:
        return {b.id for b in self.body_blocks}

    def contains_block(self, block_id: int) -> bool:
        return block_id in self.body_block_ids

    def __repr__(self):
        return (f"LoopInfo({self.loop_type}, header=B{self.header.id}, "
                f"latch=B{self.latch.id}, blocks={len(self.body_blocks)})")


def restructure_loops(cfg: 'FunctionCFG') -> List[LoopInfo]:
    """Identify and restructure all loops in the CFG.

    This is the main entry point for loop restructuring. It:
    1. Finds natural loops via back edge detection (dominator-based)
    2. Finds for-loops via pattern matching on FORNPREP/FORNLOOP/FORGPREP/FORGLOOP
    3. Classifies each loop (while, repeat, numeric for, generic for)
    4. Determines loop nesting
    5. Annotates blocks with loop membership

    Returns a list of LoopInfo objects describing each loop.
    """
    # Ensure dominance info is computed
    compute_dominators(cfg)

    loops: List[LoopInfo] = []
    found_headers: Set[int] = set()

    # Pass 1: Find for-loops via pattern matching on bytecode opcodes.
    # This catches FORNPREP/FORNLOOP and FORGPREP*/FORGLOOP pairs that
    # may not form natural loops by the strict dominator-based definition
    # (because FORNPREP jumps directly to the FORNLOOP block, making the
    # loop body block not strictly dominate the FORNLOOP block).
    for block in cfg.blocks:
        for_pat = match_for_loop(cfg, block)
        if for_pat is not None:
            loop_type = "numeric_for" if for_pat.is_numeric else "generic_for"
            info = LoopInfo(
                header=for_pat.prep_block,
                latch=for_pat.loop_block,
                body_blocks=for_pat.body_blocks,
                exit_block=for_pat.exit_block,
                loop_type=loop_type,
            )
            loops.append(info)
            found_headers.add(for_pat.prep_block.id)

    # Pass 2: Find natural loops via back edge detection (while, repeat)
    loop_edges = find_loops(cfg)

    for header, latch in loop_edges:
        if header.id in found_headers:
            continue  # Already found as a for-loop

        # Get the loop body
        body = get_loop_body(cfg, header, latch)
        body_ids = {b.id for b in body}

        # Find exit block
        exit_block = _find_loop_exit(header, latch, body_ids)

        # Classify the loop type
        loop_type = _classify_loop(cfg, header, latch, body)

        info = LoopInfo(
            header=header,
            latch=latch,
            body_blocks=body,
            exit_block=exit_block,
            loop_type=loop_type,
        )
        loops.append(info)
        found_headers.add(header.id)

    # Determine loop nesting relationships
    _compute_nesting(loops)

    # Annotate blocks with loop depth
    compute_loop_depths(cfg)

    # Store loop info on the CFG for later use
    if not hasattr(cfg, 'loops'):
        cfg.loops = []
    cfg.loops = loops

    return loops


def _classify_loop(
    cfg: 'FunctionCFG',
    header: 'BasicBlock',
    latch: 'BasicBlock',
    body: List['BasicBlock'],
) -> str:
    """Classify a loop as while, repeat, numeric_for, or generic_for.

    Classification is based on the opcodes used in the header and latch blocks.
    """
    # Check for numeric for loop
    # Look for FORNPREP in any predecessor of the header, or FORNLOOP in the latch
    for insn in latch.instructions:
        try:
            op = LuauOpcode(insn.opcode)
            if op == LuauOpcode.FORNLOOP:
                return "numeric_for"
            if op == LuauOpcode.FORGLOOP:
                return "generic_for"
        except ValueError:
            continue

    # Check header for for-prep instructions
    for insn in header.instructions:
        try:
            op = LuauOpcode(insn.opcode)
            if op == LuauOpcode.FORNPREP:
                return "numeric_for"
            if op in (LuauOpcode.FORGPREP, LuauOpcode.FORGPREP_INEXT,
                      LuauOpcode.FORGPREP_NEXT):
                return "generic_for"
        except ValueError:
            continue

    # Check if the condition is at the header (while) or latch (repeat)
    # While loop: header has a conditional branch
    header_has_cond = _block_ends_with_conditional(header)
    latch_has_cond = _block_ends_with_conditional(latch)

    if header_has_cond and not latch_has_cond:
        return "while"
    elif latch_has_cond and not header_has_cond:
        return "repeat"
    elif header_has_cond and latch_has_cond:
        # Both have conditions - this is likely a while loop where
        # the latch also has a continue condition
        return "while"
    else:
        # Unconditional loop (infinite loop, e.g., while true do ... end)
        return "while"


def _block_ends_with_conditional(block: 'BasicBlock') -> bool:
    """Check if a block ends with a conditional branch instruction."""
    if not block.instructions:
        return False

    last_insn = block.instructions[-1]
    try:
        op = LuauOpcode(last_insn.opcode)
    except ValueError:
        return False

    conditional_jumps = {
        LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT,
        LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
        LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT,
        LuauOpcode.JUMPXEQKNIL, LuauOpcode.JUMPXEQKB,
        LuauOpcode.JUMPXEQKN, LuauOpcode.JUMPXEQKS,
    }

    return op in conditional_jumps


def _find_loop_exit(
    header: 'BasicBlock',
    latch: 'BasicBlock',
    body_ids: Set[int],
) -> Optional['BasicBlock']:
    """Find the exit block of a loop.

    The exit block is a successor of the header (or latch for repeat-until)
    that is not in the loop body.
    """
    # Check header's successors first
    for succ in header.successors:
        if succ.id not in body_ids:
            return succ

    # Check latch's successors
    for succ in latch.successors:
        if succ.id not in body_ids:
            return succ

    # Check all body blocks for exits
    for bid in body_ids:
        # We need to find the block, iterate through available blocks
        for succ_block in header.successors + latch.successors:
            if succ_block.id not in body_ids:
                return succ_block

    return None


def _compute_nesting(loops: List[LoopInfo]):
    """Compute the nesting relationship between loops.

    A loop L1 is nested inside L2 if all of L1's blocks are contained
    in L2's body.
    """
    # Sort loops by body size (smallest first)
    loops.sort(key=lambda l: len(l.body_blocks))

    for i, inner in enumerate(loops):
        for j, outer in enumerate(loops):
            if i == j:
                continue
            # Check if inner is completely contained in outer
            if inner.body_block_ids <= outer.body_block_ids:
                if inner.parent_loop is None or \
                   len(inner.parent_loop.body_blocks) > len(outer.body_blocks):
                    inner.parent_loop = outer
                    inner.nesting_depth = outer.nesting_depth + 1
                    if inner not in outer.child_loops:
                        outer.child_loops.append(inner)


def find_break_targets(
    cfg: 'FunctionCFG',
    loop_info: LoopInfo,
) -> List['BasicBlock']:
    """Find blocks within the loop body that jump to the exit block.

    These represent break statements in the original source.
    """
    if loop_info.exit_block is None:
        return []

    breaks = []
    exit_id = loop_info.exit_block.id

    for block in loop_info.body_blocks:
        for succ in block.successors:
            if succ.id == exit_id and block.id != loop_info.header.id:
                breaks.append(block)

    return breaks


def find_continue_targets(
    cfg: 'FunctionCFG',
    loop_info: LoopInfo,
) -> List['BasicBlock']:
    """Find blocks within the loop body that jump back to the header.

    These represent continue statements (Luau-specific).
    Note: JUMPBACK is often used for continues.
    """
    continues = []
    header_id = loop_info.header.id

    for block in loop_info.body_blocks:
        if block.id == loop_info.latch.id:
            continue  # The latch naturally goes back to the header

        for succ in block.successors:
            if succ.id == header_id:
                # Check if this is an explicit jump (not natural flow)
                if block.instructions:
                    last = block.instructions[-1]
                    try:
                        op = LuauOpcode(last.opcode)
                        if op in (LuauOpcode.JUMP, LuauOpcode.JUMPBACK):
                            continues.append(block)
                    except ValueError:
                        pass

    return continues
