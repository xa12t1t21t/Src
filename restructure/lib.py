"""Shared utilities for CFG restructuring.

Provides helper functions used by the loop, conditional, and jump
restructuring passes.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from cfg.src.function import FunctionCFG
    from cfg.src.block import BasicBlock


def get_block_order_map(cfg: 'FunctionCFG') -> Dict[int, int]:
    """Build a map from block ID to its position in program order (by start_pc)."""
    sorted_blocks = sorted(cfg.blocks, key=lambda b: b.start_pc)
    return {b.id: idx for idx, b in enumerate(sorted_blocks)}


def is_forward_edge(src: 'BasicBlock', dst: 'BasicBlock') -> bool:
    """Check if the edge src->dst goes forward in program order."""
    return dst.start_pc > src.start_pc


def is_back_edge(src: 'BasicBlock', dst: 'BasicBlock') -> bool:
    """Check if the edge src->dst is a back edge (goes backward in PC)."""
    return dst.start_pc <= src.start_pc


def find_immediate_postdominator(
    cfg: 'FunctionCFG',
    block: 'BasicBlock',
) -> Optional['BasicBlock']:
    """Find the immediate postdominator of a block.

    The immediate postdominator is the closest block that all paths from
    the given block must pass through.

    Uses a simple forward BFS/convergence approach: follow both branches
    of a conditional and find where they meet.
    """
    if len(block.successors) <= 1:
        return block.successors[0] if block.successors else None

    if len(block.successors) != 2:
        return None

    # BFS from each successor, collecting visited blocks level by level
    left_visited: Set[int] = set()
    right_visited: Set[int] = set()

    left_frontier = [block.successors[0]]
    right_frontier = [block.successors[1]]

    max_depth = len(cfg.blocks) + 1

    for _ in range(max_depth):
        # Expand left
        new_left = []
        for b in left_frontier:
            if b.id in left_visited:
                continue
            left_visited.add(b.id)
            new_left.extend(b.successors)
        left_frontier = new_left

        # Expand right
        new_right = []
        for b in right_frontier:
            if b.id in right_visited:
                continue
            right_visited.add(b.id)
            new_right.extend(b.successors)
        right_frontier = new_right

        # Check for convergence
        common = left_visited & right_visited
        if common:
            # Return the common block with the smallest start_pc
            best = None
            for b in cfg.blocks:
                if b.id in common:
                    if best is None or b.start_pc < best.start_pc:
                        best = b
            return best

    return None


def collect_blocks_between(
    cfg: 'FunctionCFG',
    start: 'BasicBlock',
    end: 'BasicBlock',
    include_start: bool = True,
    include_end: bool = False,
) -> List['BasicBlock']:
    """Collect all blocks between start and end in program order.

    Returns blocks whose start_pc is between start.start_pc and end.start_pc.
    """
    result = []
    for block in sorted(cfg.blocks, key=lambda b: b.start_pc):
        if include_start and block.id == start.id:
            result.append(block)
        elif include_end and block.id == end.id:
            result.append(block)
        elif block.start_pc > start.start_pc and block.start_pc < end.start_pc:
            result.append(block)
    return result


def find_single_entry_region(
    blocks: List['BasicBlock'],
    entry: 'BasicBlock',
) -> bool:
    """Check if a set of blocks forms a single-entry region.

    A single-entry region has exactly one entry point: all edges from
    outside the region enter through the entry block.
    """
    block_ids = {b.id for b in blocks}

    for block in blocks:
        if block.id == entry.id:
            continue
        for pred in block.predecessors:
            if pred.id not in block_ids:
                return False  # This block has an external predecessor

    return True


def find_exit_blocks(
    blocks: List['BasicBlock'],
) -> List['BasicBlock']:
    """Find blocks in a region that have successors outside the region."""
    block_ids = {b.id for b in blocks}
    exits = []

    for block in blocks:
        for succ in block.successors:
            if succ.id not in block_ids:
                exits.append(block)
                break

    return exits


def merge_blocks(
    cfg: 'FunctionCFG',
    block_a: 'BasicBlock',
    block_b: 'BasicBlock',
) -> 'BasicBlock':
    """Merge two consecutive blocks into one.

    Requires that block_a's only successor is block_b, and block_b's
    only predecessor is block_a.

    Returns block_a (now containing both blocks' contents).
    """
    assert len(block_a.successors) == 1 and block_a.successors[0] == block_b
    assert len(block_b.predecessors) == 1 and block_b.predecessors[0] == block_a

    # Merge instructions
    block_a.instructions.extend(block_b.instructions)
    block_a.end_pc = block_b.end_pc

    # Merge statements
    block_a.statements.extend(block_b.statements)

    # Merge SSA info
    block_a.defs |= block_b.defs
    block_a.phi_functions.extend(block_b.phi_functions)

    # Update edges
    block_a.successors = block_b.successors[:]
    for succ in block_a.successors:
        # Replace block_b with block_a in successor's predecessors
        succ.predecessors = [
            block_a if p == block_b else p for p in succ.predecessors
        ]

    # Transfer loop properties
    if block_b.is_loop_header:
        block_a.is_loop_header = True
    if block_b.is_loop_latch:
        block_a.is_loop_latch = True
    block_a.loop_depth = max(block_a.loop_depth, block_b.loop_depth)

    # Remove block_b from CFG
    cfg.blocks = [b for b in cfg.blocks if b.id != block_b.id]
    if block_b.id in cfg._id_to_block:
        del cfg._id_to_block[block_b.id]
    # Update PC mapping
    for pc, block in list(cfg._pc_to_block.items()):
        if block == block_b:
            cfg._pc_to_block[pc] = block_a

    return block_a
