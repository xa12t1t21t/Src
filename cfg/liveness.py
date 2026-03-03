"""Liveness analysis for SSA destruction.

Computes live-in and live-out sets for each basic block using the
standard backward dataflow analysis.

A variable is live at a point if it may be used in the future before
being redefined.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ...function import FunctionCFG
    from ...block import BasicBlock


def compute_liveness(cfg: 'FunctionCFG') -> Dict[int, Dict[str, Set[str]]]:
    """Compute live-in and live-out sets for each block.

    Uses the standard backward iterative dataflow analysis:
        live_in[B]  = use[B] | (live_out[B] - def[B])
        live_out[B] = union of live_in[S] for each successor S of B

    Also accounts for phi function uses: a phi source from block B
    makes the source variable live-out of B.

    Returns:
        Dict mapping block_id -> {"live_in": set, "live_out": set}
    """
    blocks = cfg.blocks
    if not blocks:
        return {}

    # Initialize sets
    live_in: Dict[int, Set[str]] = {b.id: set() for b in blocks}
    live_out: Dict[int, Set[str]] = {b.id: set() for b in blocks}

    # Compute use and def sets considering SSA names
    block_use: Dict[int, Set[str]] = {}
    block_def: Dict[int, Set[str]] = {}

    for block in blocks:
        uses = set()
        defs = set()

        # Phi functions: the target is defined, sources are used
        for phi in block.phi_functions:
            if phi.target:
                defs.add(phi.target)

        # Instructions: use SSA maps if available, otherwise use raw reg names
        if hasattr(block, 'ssa_use_map') and block.ssa_use_map:
            for key, ssa_name in block.ssa_use_map.items():
                if ssa_name not in defs:
                    uses.add(ssa_name)
            for key, ssa_name in getattr(block, 'ssa_def_map', {}).items():
                defs.add(ssa_name)
        else:
            # Fall back to raw register names
            for var in block.uses:
                if var not in defs:
                    uses.add(var)
            defs.update(block.defs)

        block_use[block.id] = uses
        block_def[block.id] = defs

    # Add phi-function source contributions to live-out of predecessor blocks
    phi_live_out: Dict[int, Set[str]] = defaultdict(set)
    for block in blocks:
        for phi in block.phi_functions:
            for pred_id, src_name in phi.sources:
                phi_live_out[pred_id].add(src_name)

    # Iterative backward dataflow analysis
    changed = True
    max_iterations = len(blocks) * 10 + 100  # safety limit
    iteration = 0

    while changed and iteration < max_iterations:
        changed = False
        iteration += 1

        # Process blocks in reverse order (backward analysis)
        for block in reversed(blocks):
            bid = block.id

            # Compute new live_out: union of live_in of all successors
            new_out = set()
            for succ in block.successors:
                new_out |= live_in[succ.id]

            # Add phi contributions
            new_out |= phi_live_out.get(bid, set())

            # Compute new live_in: use | (live_out - def)
            new_in = block_use[bid] | (new_out - block_def[bid])

            if new_in != live_in[bid] or new_out != live_out[bid]:
                changed = True
                live_in[bid] = new_in
                live_out[bid] = new_out

    # Store results in blocks and build return value
    result = {}
    for block in blocks:
        block.live_in = live_in[block.id]
        block.live_out = live_out[block.id]
        result[block.id] = {
            "live_in": live_in[block.id],
            "live_out": live_out[block.id],
        }

    return result


def is_live_at(cfg: 'FunctionCFG', var: str, block_id: int) -> bool:
    """Check if a variable is live at the entry of a given block.

    Requires that compute_liveness has been called first.
    """
    block = cfg.get_block_by_id(block_id)
    if block is None:
        return False
    return var in block.live_in


def get_live_range(cfg: 'FunctionCFG', var: str) -> Set[int]:
    """Get the set of block IDs where a variable is live (in live_in or live_out).

    Requires that compute_liveness has been called first.
    """
    live_blocks = set()
    for block in cfg.blocks:
        if var in block.live_in or var in block.live_out:
            live_blocks.add(block.id)
    return live_blocks


def compute_interference(cfg: 'FunctionCFG') -> Dict[str, Set[str]]:
    """Build an interference graph: variables that are simultaneously live.

    Two variables interfere if they are both live at some point.
    Returns a dict mapping each variable to the set of variables it interferes with.

    Requires that compute_liveness has been called first.
    """
    interference: Dict[str, Set[str]] = defaultdict(set)

    for block in cfg.blocks:
        # At each point in the block, variables in the same live set interfere
        live_set = set(block.live_out)

        # Walk instructions in reverse
        for insn in reversed(block.instructions):
            # Variables currently live interfere with each other
            live_list = list(live_set)
            for i in range(len(live_list)):
                for j in range(i + 1, len(live_list)):
                    interference[live_list[i]].add(live_list[j])
                    interference[live_list[j]].add(live_list[i])

            # Update live set: remove defs, add uses
            if hasattr(block, 'ssa_def_map'):
                for key, ssa_name in block.ssa_def_map.items():
                    if key[0] == insn.pc:
                        live_set.discard(ssa_name)
            if hasattr(block, 'ssa_use_map'):
                for key, ssa_name in block.ssa_use_map.items():
                    if key[0] == insn.pc:
                        live_set.add(ssa_name)

    return dict(interference)
