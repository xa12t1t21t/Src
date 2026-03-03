"""Shared utilities for CFG manipulation.

Provides core graph algorithms: dominator computation, loop detection,
and block ordering.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from .block import BasicBlock


def compute_dominators(cfg) -> Dict[int, int]:
    """Compute immediate dominators using the iterative dominator algorithm.

    Uses the Cooper-Harvey-Kennedy algorithm (a simplified Lengauer-Tarjan).
    Returns a dict mapping each block ID to its immediate dominator's block ID.
    The entry block dominates itself.

    Reference: "A Simple, Fast Dominance Algorithm" by Cooper, Harvey, Kennedy.
    """
    blocks = cfg.blocks
    if not blocks:
        return {}

    entry = cfg.entry_block

    # Get reverse postorder
    rpo = _reverse_postorder(entry)
    rpo_index = {block.id: idx for idx, block in enumerate(rpo)}

    # Initialize: entry dominates itself, all others are undefined
    idom: Dict[int, int] = {}
    idom[entry.id] = entry.id

    id_to_block = {b.id: b for b in blocks}

    def intersect(b1_id: int, b2_id: int) -> int:
        """Find the common dominator of two blocks."""
        finger1 = b1_id
        finger2 = b2_id
        while finger1 != finger2:
            while rpo_index.get(finger1, float('inf')) > rpo_index.get(finger2, float('inf')):
                finger1 = idom[finger1]
            while rpo_index.get(finger2, float('inf')) > rpo_index.get(finger1, float('inf')):
                finger2 = idom[finger2]
        return finger1

    # Iterate until stable
    changed = True
    while changed:
        changed = False
        for block in rpo:
            if block.id == entry.id:
                continue

            # Find first processed predecessor
            new_idom = None
            for pred in block.predecessors:
                if pred.id in idom:
                    if new_idom is None:
                        new_idom = pred.id
                    else:
                        new_idom = intersect(new_idom, pred.id)

            if new_idom is not None and idom.get(block.id) != new_idom:
                idom[block.id] = new_idom
                changed = True

    cfg.dominators = idom
    return idom


def compute_dominance_frontiers(cfg) -> Dict[int, Set[int]]:
    """Compute the dominance frontier for each block.

    The dominance frontier of a block B is the set of all blocks D such that
    B dominates a predecessor of D but does not strictly dominate D.

    This is needed for SSA phi-function placement.
    """
    if not cfg.dominators:
        compute_dominators(cfg)

    idom = cfg.dominators
    frontiers: Dict[int, Set[int]] = {b.id: set() for b in cfg.blocks}

    for block in cfg.blocks:
        if len(block.predecessors) < 2:
            continue

        for pred in block.predecessors:
            runner = pred.id
            while runner != idom.get(block.id, block.id):
                frontiers[runner].add(block.id)
                if runner == idom.get(runner):
                    break  # reached entry
                runner = idom.get(runner, runner)

    # Store in blocks
    for block in cfg.blocks:
        block.dominance_frontier = frontiers.get(block.id, set())

    return frontiers


def dominates(cfg, a_id: int, b_id: int) -> bool:
    """Check if block a dominates block b.

    Block a dominates block b if a is on every path from the entry to b.
    """
    if not cfg.dominators:
        compute_dominators(cfg)

    idom = cfg.dominators
    current = b_id
    while current != a_id:
        parent = idom.get(current)
        if parent is None or parent == current:
            # Reached the root without finding a_id
            return current == a_id
        current = parent
    return True


def find_loops(cfg) -> List[Tuple[BasicBlock, BasicBlock]]:
    """Find natural loops in the CFG.

    A natural loop is identified by a back edge (latch -> header) where
    the header dominates the latch. Returns a list of (header, latch) pairs.
    """
    if not cfg.dominators:
        compute_dominators(cfg)

    loops = []
    id_to_block = {b.id: b for b in cfg.blocks}

    for block in cfg.blocks:
        for succ in block.successors:
            # A back edge exists if the successor dominates the block
            if dominates(cfg, succ.id, block.id):
                succ.is_loop_header = True
                block.is_loop_latch = True
                loops.append((succ, block))

    return loops


def get_loop_body(cfg, header: BasicBlock, latch: BasicBlock) -> List[BasicBlock]:
    """Get all blocks that form the body of a natural loop.

    The loop body consists of all blocks that can reach the latch
    without going through the header (plus the header itself).
    Uses a backward traversal from the latch.
    """
    body = {header.id, latch.id}
    worklist = [latch]

    while worklist:
        block = worklist.pop()
        for pred in block.predecessors:
            if pred.id not in body:
                body.add(pred.id)
                worklist.append(pred)

    id_to_block = {b.id: b for b in cfg.blocks}
    return [id_to_block[bid] for bid in sorted(body)]


def get_blocks_in_order(cfg) -> List[BasicBlock]:
    """Get blocks in reverse postorder (RPO).

    RPO ensures that (in an acyclic graph) each block is visited after
    all of its predecessors. This is the standard order for dataflow analyses.
    """
    if cfg.entry_block is None:
        return []
    return _reverse_postorder(cfg.entry_block)


def _reverse_postorder(entry: BasicBlock) -> List[BasicBlock]:
    """Compute reverse postorder traversal starting from the entry block."""
    visited = set()
    postorder = []

    def dfs(block: BasicBlock):
        if block.id in visited:
            return
        visited.add(block.id)
        for succ in block.successors:
            dfs(succ)
        postorder.append(block)

    dfs(entry)
    postorder.reverse()
    return postorder


def compute_loop_depths(cfg) -> None:
    """Compute the loop nesting depth for each block.

    A block inside N nested loops has depth N. Blocks not in any loop have depth 0.
    """
    loops = find_loops(cfg)

    # Reset all depths
    for block in cfg.blocks:
        block.loop_depth = 0

    for header, latch in loops:
        body = get_loop_body(cfg, header, latch)
        for block in body:
            block.loop_depth += 1


def find_reachable_blocks(entry: BasicBlock) -> Set[int]:
    """Find all blocks reachable from the entry block."""
    visited = set()
    worklist = deque([entry])

    while worklist:
        block = worklist.popleft()
        if block.id in visited:
            continue
        visited.add(block.id)
        for succ in block.successors:
            if succ.id not in visited:
                worklist.append(succ)

    return visited


def remove_unreachable_blocks(cfg) -> List[BasicBlock]:
    """Remove blocks not reachable from the entry and return removed blocks."""
    if cfg.entry_block is None:
        return []

    reachable = find_reachable_blocks(cfg.entry_block)
    removed = []

    for block in cfg.blocks[:]:
        if block.id not in reachable:
            # Remove edges from/to this block
            for succ in block.successors[:]:
                block.remove_successor(succ)
            for pred in block.predecessors[:]:
                pred.remove_successor(block)
            removed.append(block)

    cfg.blocks = [b for b in cfg.blocks if b.id in reachable]
    return removed
