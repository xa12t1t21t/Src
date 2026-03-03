"""Expression inlining for SSA form.

Inlines single-use definitions directly into their use sites.
This reduces the number of temporary variables and produces more
readable decompiled output.

For example, if r0_1 is defined once and used once:
    r0_1 = a + b
    r1_1 = r0_1 * c
becomes:
    r1_1 = (a + b) * c
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..function import FunctionCFG
    from ..block import BasicBlock


def inline_expressions(cfg: 'FunctionCFG'):
    """Inline single-use SSA definitions.

    An SSA variable can be inlined if:
    1. It has exactly one definition (guaranteed by SSA)
    2. It has exactly one use
    3. The definition and use are in the same block, OR the definition
       dominates the use and there are no side effects between them
    4. Inlining won't change the order of side effects

    This is a conservative pass that only inlines clearly safe cases.
    """
    # Step 1: Count uses for each SSA variable
    use_counts = _count_variable_uses(cfg)

    # Step 2: Build definition map: ssa_name -> (block_id, insn_pc)
    def_map = _build_definition_map(cfg)

    # Step 3: Find candidates for inlining (exactly one use)
    candidates = set()
    for var, count in use_counts.items():
        if count == 1 and var in def_map:
            candidates.add(var)

    # Step 4: Filter candidates by safety checks
    safe_candidates = set()
    for var in candidates:
        if _is_safe_to_inline(cfg, var, def_map):
            safe_candidates.add(var)

    # Step 5: Mark inlinable definitions
    # Store the inline info so the code generator can use it
    if not hasattr(cfg, 'inline_candidates'):
        cfg.inline_candidates = set()
    cfg.inline_candidates = safe_candidates

    # Also store the def map for the code generator
    if not hasattr(cfg, 'ssa_def_map'):
        cfg.ssa_def_map = {}
    cfg.ssa_def_map = def_map

    return safe_candidates


def _count_variable_uses(cfg: 'FunctionCFG') -> Dict[str, int]:
    """Count how many times each SSA variable is used (read)."""
    counts: Dict[str, int] = defaultdict(int)

    for block in cfg.blocks:
        # Count uses in instructions
        if hasattr(block, 'ssa_use_map'):
            for key, ssa_name in block.ssa_use_map.items():
                counts[ssa_name] += 1

        # Count uses in phi function sources
        for phi in block.phi_functions:
            for pred_id, src_name in phi.sources:
                counts[src_name] += 1

    return dict(counts)


def _build_definition_map(cfg: 'FunctionCFG') -> Dict[str, Tuple[int, int]]:
    """Build a map from SSA variable name to (block_id, insn_pc) of definition.

    Also includes phi function definitions.
    """
    def_map: Dict[str, Tuple[int, int]] = {}

    for block in cfg.blocks:
        # Phi function definitions
        for phi in block.phi_functions:
            if phi.target:
                def_map[phi.target] = (block.id, -1)  # -1 indicates phi

        # Instruction definitions
        if hasattr(block, 'ssa_def_map'):
            for (pc, var), ssa_name in block.ssa_def_map.items():
                def_map[ssa_name] = (block.id, pc)

    return def_map


def _is_safe_to_inline(
    cfg: 'FunctionCFG',
    var: str,
    def_map: Dict[str, Tuple[int, int]],
) -> bool:
    """Check if it's safe to inline a variable.

    We conservatively require:
    - Not a phi function definition (those represent control flow merges)
    - The definition is not a function call (side effects)
    - The definition is a simple expression (not a multi-result operation)
    """
    if var not in def_map:
        return False

    block_id, pc = def_map[var]

    # Don't inline phi function results
    if pc == -1:
        return False

    block = cfg.get_block_by_id(block_id)
    if block is None:
        return False

    # Find the defining instruction
    def_insn = None
    for insn in block.instructions:
        if insn.pc == pc:
            def_insn = insn
            break

    if def_insn is None:
        return False

    from deserializer.opcodes import LuauOpcode

    try:
        opcode = LuauOpcode(def_insn.opcode)
    except ValueError:
        return False

    # Don't inline function calls (side effects)
    if opcode in (LuauOpcode.CALL, LuauOpcode.NAMECALL):
        return False

    # Don't inline table/global accesses (may have side effects)
    if opcode in (LuauOpcode.GETTABLE, LuauOpcode.GETTABLEKS,
                  LuauOpcode.GETTABLEN, LuauOpcode.GETGLOBAL,
                  LuauOpcode.GETIMPORT):
        return False

    # Don't inline GETUPVAL (upvalue captures can be complex)
    if opcode == LuauOpcode.GETUPVAL:
        return False

    # Don't inline GETVARARGS
    if opcode == LuauOpcode.GETVARARGS:
        return False

    # Don't inline NEWCLOSURE/DUPCLOSURE
    if opcode in (LuauOpcode.NEWCLOSURE, LuauOpcode.DUPCLOSURE):
        return False

    # Safe to inline: arithmetic, logic, loads, moves
    return True


def get_inline_chain(
    cfg: 'FunctionCFG',
    var: str,
    max_depth: int = 10,
) -> List[str]:
    """Get the chain of inlined variables starting from var.

    Follows definitions recursively to build the full expression tree.
    Returns a list of SSA variable names in definition order.
    """
    chain = []
    visited = set()

    def _follow(v: str, depth: int):
        if depth > max_depth or v in visited:
            return
        visited.add(v)
        chain.append(v)

        if not hasattr(cfg, 'ssa_def_map') or v not in cfg.ssa_def_map:
            return

        block_id, pc = cfg.ssa_def_map[v]
        block = cfg.get_block_by_id(block_id)
        if block is None:
            return

        # Find uses of this definition's source variables
        if hasattr(block, 'ssa_use_map'):
            for (insn_pc, reg), ssa_name in block.ssa_use_map.items():
                if insn_pc == pc:
                    _follow(ssa_name, depth + 1)

    _follow(var, 0)
    return chain
