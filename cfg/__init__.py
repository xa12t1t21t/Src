"""SSA destruction sub-package.

Converts SSA form back to normal form by replacing phi functions
with parallel copy operations.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple, TYPE_CHECKING

from ...block import BasicBlock, PhiFunction

if TYPE_CHECKING:
    from ...function import FunctionCFG


def destruct_ssa(cfg: 'FunctionCFG'):
    """Remove phi functions and insert parallel copies.

    The standard SSA destruction algorithm:
    1. For each phi function "x = phi(a from B1, b from B2, ...)",
       insert a copy "x = a" at the end of B1, "x = b" at the end of B2, etc.
    2. Sequentialize parallel copies to avoid conflicts using a dependency analysis.
    3. Remove all phi functions.

    This approach handles the "lost copy" and "swap" problems.
    """
    from .liveness import compute_liveness

    # Compute liveness to know which values are still needed
    liveness = compute_liveness(cfg)

    # Step 1: Collect all copies that need to be inserted
    # Maps block_id -> list of (dest_ssa_name, src_ssa_name, register) tuples
    copies_to_insert: Dict[int, List[Tuple[str, str, int]]] = defaultdict(list)

    for block in cfg.blocks:
        for phi in block.phi_functions:
            for pred_id, src_name in phi.sources:
                copies_to_insert[pred_id].append(
                    (phi.target, src_name, phi.register)
                )

    # Step 2: Sequentialize parallel copies and insert them
    for block_id, copies in copies_to_insert.items():
        block = cfg.get_block_by_id(block_id)
        if block is None:
            continue

        sequenced = _sequentialize_copies(copies)

        # Store the copy sequence as metadata on the block
        if not hasattr(block, 'ssa_copies'):
            block.ssa_copies = []
        block.ssa_copies.extend(sequenced)

    # Step 3: Remove phi functions from all blocks
    for block in cfg.blocks:
        block.phi_functions.clear()


def _sequentialize_copies(
    copies: List[Tuple[str, str, int]]
) -> List[Tuple[str, str, int]]:
    """Convert parallel copies to a sequential ordering.

    Given parallel copies {(dst1, src1), (dst2, src2), ...}, find a sequential
    ordering that produces the same result. Uses a topological sort on the
    dependency graph, with temporary variables for cycles.

    Args:
        copies: List of (dest_name, src_name, register) triples.

    Returns:
        Ordered list of (dest, src, register) copies to execute sequentially.
    """
    if not copies:
        return []

    # Remove trivial copies (self-copies)
    copies = [(d, s, r) for d, s, r in copies if d != s]
    if not copies:
        return []

    # Build dependency graph: dest -> src
    # A copy dst=src depends on src being available (not yet overwritten)
    result = []
    remaining = list(copies)
    temp_counter = [0]

    # Keep processing until all copies are placed
    max_iterations = len(remaining) * 2 + 10  # safety limit
    iteration = 0

    while remaining and iteration < max_iterations:
        iteration += 1
        progress = False

        # Find a copy whose destination is not a source of another remaining copy
        i = 0
        while i < len(remaining):
            dest, src, reg = remaining[i]
            # Check if dest is used as a source by another copy
            is_source = any(s == dest for d, s, _ in remaining if d != dest)
            if not is_source:
                result.append(remaining.pop(i))
                progress = True
            else:
                i += 1

        if not progress and remaining:
            # We have a cycle. Break it by introducing a temporary.
            dest, src, reg = remaining[0]
            temp_name = f"__ssa_tmp_{temp_counter[0]}"
            temp_counter[0] += 1

            # Save src to temp, then we can overwrite it
            result.append((temp_name, src, reg))

            # Replace src in remaining copies with temp
            remaining[0] = (dest, temp_name, reg)

    # Add any remaining copies (shouldn't happen with correct algorithm)
    result.extend(remaining)

    return result
