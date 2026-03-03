"""SSA construction algorithm.

Implements the standard SSA construction algorithm:
1. Compute dominance frontiers
2. Place phi functions at iterated dominance frontiers
3. Rename variables using a dominator tree walk

Reference: Cytron et al., "Efficiently Computing Static Single Assignment
Form and the Control Dependence Graph", TOPLAS 1991.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, TYPE_CHECKING

from ..block import BasicBlock, PhiFunction
from ..lib import compute_dominators, compute_dominance_frontiers, get_blocks_in_order

if TYPE_CHECKING:
    from ..function import FunctionCFG


def construct_ssa(cfg: 'FunctionCFG'):
    """Convert the CFG to SSA form.

    After this transformation:
    - Each variable (register) is defined exactly once
    - Phi functions are placed at join points where needed
    - All references use the SSA-renamed version (e.g., r0_1, r0_2)
    """
    # Step 0: Compute dominance information
    compute_dominators(cfg)
    compute_dominance_frontiers(cfg)

    # Step 1: Collect all variables (registers) and their definition sites
    all_vars = set()
    def_sites: Dict[str, Set[int]] = defaultdict(set)  # var -> set of block IDs

    for block in cfg.blocks:
        for var in block.defs:
            all_vars.add(var)
            def_sites[var].add(block.id)

    # Step 2: Place phi functions using iterated dominance frontier
    phi_placements = _place_phi_functions(cfg, all_vars, def_sites)

    # Create PhiFunction objects
    for block_id, variables in phi_placements.items():
        block = cfg.get_block_by_id(block_id)
        if block is None:
            continue
        for var in variables:
            # Extract register number from variable name (e.g., "r0" -> 0)
            reg_num = _extract_reg_number(var)
            phi = PhiFunction(
                target="",  # will be assigned during renaming
                register=reg_num,
                sources=[],  # will be filled during renaming
            )
            block.phi_functions.append(phi)

    # Step 3: Rename variables
    _rename_variables(cfg, all_vars)


def _place_phi_functions(
    cfg: 'FunctionCFG',
    all_vars: Set[str],
    def_sites: Dict[str, Set[int]],
) -> Dict[int, Set[str]]:
    """Place phi functions using the iterated dominance frontier algorithm.

    For each variable v:
    1. Start with the set of blocks that define v
    2. For each block in that set, add phi functions at its dominance frontier
    3. The phi function itself is a definition, so repeat until stable

    Returns a dict mapping block_id -> set of variables needing phi functions.
    """
    phi_placements: Dict[int, Set[str]] = defaultdict(set)

    for var in all_vars:
        # Worklist = blocks that define this variable
        worklist = deque(def_sites[var])
        has_phi = set()  # blocks where phi for this var is already placed
        ever_on_worklist = set(def_sites[var])

        while worklist:
            block_id = worklist.popleft()
            block = cfg.get_block_by_id(block_id)
            if block is None:
                continue

            for frontier_id in block.dominance_frontier:
                if frontier_id not in has_phi:
                    has_phi.add(frontier_id)
                    phi_placements[frontier_id].add(var)

                    # The phi function is itself a definition of var
                    if frontier_id not in ever_on_worklist:
                        ever_on_worklist.add(frontier_id)
                        worklist.append(frontier_id)

    return phi_placements


def _rename_variables(cfg: 'FunctionCFG', all_vars: Set[str]):
    """Rename variables to SSA form using a dominator tree walk.

    Uses a stack-based approach: for each variable, maintain a counter
    and a stack of current definitions. Walk the dominator tree in preorder,
    pushing new names when encountering definitions and popping when
    backtracking.
    """
    # Counter for generating unique SSA names
    counters: Dict[str, int] = {var: 0 for var in all_vars}
    # Stack of current SSA name for each variable
    stacks: Dict[str, List[str]] = {var: [] for var in all_vars}

    # Build dominator tree children
    idom = cfg.dominators
    dom_children: Dict[int, List[int]] = defaultdict(list)
    for block_id, parent_id in idom.items():
        if block_id != parent_id:
            dom_children[parent_id].append(block_id)

    # Initialize: parameters and initial register values get version 0
    for var in all_vars:
        initial_name = f"{var}_0"
        counters[var] = 1
        stacks[var].append(initial_name)

    def _new_name(var: str) -> str:
        """Generate a new SSA name for a variable."""
        idx = counters[var]
        counters[var] = idx + 1
        name = f"{var}_{idx}"
        stacks[var].append(name)
        return name

    def _current_name(var: str) -> str:
        """Get the current SSA name for a variable."""
        if stacks[var]:
            return stacks[var][-1]
        # Variable used before definition - create initial version
        return _new_name(var)

    def _rename_block(block: BasicBlock):
        """Rename all variables in a block and its dominator tree children."""
        # Track how many names we pushed so we can pop them when backtracking
        push_counts: Dict[str, int] = defaultdict(int)

        # Rename phi function targets
        for phi in block.phi_functions:
            var = f"r{phi.register}"
            new = _new_name(var)
            phi.target = new
            push_counts[var] += 1

        # Rename uses and defs in instructions
        # We store the SSA name mappings in a dict attached to the block
        if not hasattr(block, 'ssa_use_map'):
            block.ssa_use_map = {}  # maps (insn_pc, var) -> ssa_name for uses
        if not hasattr(block, 'ssa_def_map'):
            block.ssa_def_map = {}  # maps (insn_pc, var) -> ssa_name for defs

        for insn in block.instructions:
            from ..function import _get_insn_reads_writes
            from deserializer.opcodes import LuauOpcode
            try:
                opcode = LuauOpcode(insn.opcode)
            except ValueError:
                continue

            reads, writes = _get_insn_reads_writes(insn, opcode)

            # Rename uses (reads) to current SSA names
            for var in reads:
                ssa_name = _current_name(var)
                block.ssa_use_map[(insn.pc, var)] = ssa_name

            # Rename defs (writes) to new SSA names
            for var in writes:
                new = _new_name(var)
                block.ssa_def_map[(insn.pc, var)] = new
                push_counts[var] += 1

        # Fill in phi function sources in successor blocks
        for succ in block.successors:
            for phi in succ.phi_functions:
                var = f"r{phi.register}"
                current = _current_name(var)
                phi.sources.append((block.id, current))

        # Recurse into dominator tree children
        for child_id in dom_children.get(block.id, []):
            child = cfg.get_block_by_id(child_id)
            if child is not None:
                _rename_block(child)

        # Pop names we pushed in this block
        for var, count in push_counts.items():
            for _ in range(count):
                if stacks[var]:
                    stacks[var].pop()

    # Start from the entry block
    if cfg.entry_block is not None:
        _rename_block(cfg.entry_block)


def _extract_reg_number(var: str) -> int:
    """Extract the register number from a variable name like 'r0' or 'r12'."""
    if var.startswith('r'):
        try:
            return int(var[1:])
        except ValueError:
            pass
    return -1
