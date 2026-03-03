"""Conditional restructuring pass.

Identifies and restructures conditional branches in the CFG into
proper if/elseif/else chains. Handles:
- Simple if-then
- If-then-else
- If-elseif-else chains
- Nested conditionals

The restructuring annotates the CFG with conditional pattern information
that the structuring pass uses to emit AST IfStatement nodes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from cfg.src.pattern import match_if_else, IfPattern
from cfg.src.lib import dominates, compute_dominators

from deserializer.opcodes import LuauOpcode

if TYPE_CHECKING:
    from cfg.src.function import FunctionCFG
    from cfg.src.block import BasicBlock


@dataclass
class ConditionalInfo:
    """Information about a restructured conditional."""
    # The block containing the condition test
    condition_block: 'BasicBlock' = None
    # The then-branch entry block
    then_entry: Optional['BasicBlock'] = None
    # All blocks in the then-branch
    then_blocks: List['BasicBlock'] = field(default_factory=list)
    # The else-branch entry block (None if no else)
    else_entry: Optional['BasicBlock'] = None
    # All blocks in the else-branch
    else_blocks: List['BasicBlock'] = field(default_factory=list)
    # Elseif chains: list of (condition_block, then_blocks) pairs
    elseif_chains: List[Tuple['BasicBlock', List['BasicBlock']]] = field(default_factory=list)
    # The block where branches merge
    merge_block: Optional['BasicBlock'] = None
    # Whether this is part of a short-circuit expression (and/or)
    is_short_circuit: bool = False


def restructure_conditionals(cfg: 'FunctionCFG') -> List[ConditionalInfo]:
    """Identify and restructure if/elseif/else chains in the CFG.

    This is the main entry point for conditional restructuring. It:
    1. Finds all conditional branches (blocks with 2 successors)
    2. Determines branch structure (if-then, if-else, if-elseif-else)
    3. Identifies short-circuit expressions (and/or)
    4. Annotates the CFG with conditional info

    Returns a list of ConditionalInfo objects.
    """
    compute_dominators(cfg)

    conditionals: List[ConditionalInfo] = []
    processed: Set[int] = set()

    # Process blocks in program order
    sorted_blocks = sorted(cfg.blocks, key=lambda b: b.start_pc)

    for block in sorted_blocks:
        if block.id in processed:
            continue

        if len(block.successors) != 2:
            continue

        if not block.instructions:
            continue

        # Skip blocks inside loops that are loop conditions (handled by loop restructuring)
        if block.is_loop_header:
            continue

        # Try to match an if-else pattern
        pattern = match_if_else(cfg, block)
        if pattern is None:
            continue

        # Try to extend into an elseif chain
        info = _build_conditional_chain(cfg, block, pattern, processed)
        if info is not None:
            conditionals.append(info)
            processed.add(block.id)

    # Store on CFG for later use
    if not hasattr(cfg, 'conditionals'):
        cfg.conditionals = []
    cfg.conditionals = conditionals

    return conditionals


def _build_conditional_chain(
    cfg: 'FunctionCFG',
    start_block: 'BasicBlock',
    initial_pattern: IfPattern,
    processed: Set[int],
) -> Optional[ConditionalInfo]:
    """Build a complete if/elseif/else chain from a starting conditional.

    Follows the else branch to see if it contains another conditional,
    building up an elseif chain.
    """
    info = ConditionalInfo(condition_block=start_block)

    # Determine then and else blocks
    then_block = initial_pattern.then_block
    else_block = initial_pattern.else_block
    merge_block = initial_pattern.merge_block

    info.then_entry = then_block
    info.then_blocks = _collect_branch_blocks(cfg, then_block, merge_block, start_block)
    info.merge_block = merge_block

    if else_block is None or else_block == merge_block:
        # Simple if-then (no else)
        info.else_entry = None
        return info

    # Check if the else block is itself a conditional (elseif chain)
    current_else = else_block
    while current_else is not None and current_else != merge_block:
        if (len(current_else.successors) == 2 and
                current_else.instructions and
                _is_conditional_branch(current_else)):

            # This is an elseif
            elseif_pattern = match_if_else(cfg, current_else)
            if elseif_pattern is not None:
                elseif_then_blocks = _collect_branch_blocks(
                    cfg, elseif_pattern.then_block, merge_block, current_else
                )
                info.elseif_chains.append((current_else, elseif_then_blocks))
                processed.add(current_else.id)

                # Continue to the next else block
                current_else = elseif_pattern.else_block
                continue

        # This is the final else block
        info.else_entry = current_else
        info.else_blocks = _collect_branch_blocks(cfg, current_else, merge_block, start_block)
        break

    return info


def _collect_branch_blocks(
    cfg: 'FunctionCFG',
    entry: 'BasicBlock',
    merge: Optional['BasicBlock'],
    cond_block: 'BasicBlock',
) -> List['BasicBlock']:
    """Collect all blocks belonging to a branch (then or else).

    Collects blocks reachable from entry that don't go past the merge block.
    """
    if entry is None:
        return []

    blocks = []
    visited = set()
    worklist = [entry]

    merge_id = merge.id if merge is not None else -1

    while worklist:
        block = worklist.pop(0)
        if block.id in visited:
            continue
        if block.id == merge_id:
            continue
        if block.id == cond_block.id:
            continue

        visited.add(block.id)
        blocks.append(block)

        for succ in block.successors:
            if succ.id not in visited and succ.id != merge_id:
                worklist.append(succ)

    return blocks


def _is_conditional_branch(block: 'BasicBlock') -> bool:
    """Check if a block ends with a conditional branch."""
    if not block.instructions:
        return False

    last = block.instructions[-1]
    try:
        op = LuauOpcode(last.opcode)
    except ValueError:
        return False

    return op in {
        LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT,
        LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
        LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT,
        LuauOpcode.JUMPXEQKNIL, LuauOpcode.JUMPXEQKB,
        LuauOpcode.JUMPXEQKN, LuauOpcode.JUMPXEQKS,
    }


def detect_short_circuit(
    cfg: 'FunctionCFG',
    block: 'BasicBlock',
) -> Optional[str]:
    """Detect if a conditional is part of a short-circuit expression.

    Short-circuit `and`:
        if A then goto check_B else goto false_result
        check_B: if B then goto true_result else goto false_result

    Short-circuit `or`:
        if A then goto true_result else goto check_B
        check_B: if B then goto true_result else goto false_result

    Returns "and", "or", or None.
    """
    if len(block.successors) != 2:
        return None

    fall_through = block.successors[0]
    jump_target = block.successors[1]

    if not block.instructions:
        return None

    last = block.instructions[-1]
    try:
        op = LuauOpcode(last.opcode)
    except ValueError:
        return None

    # Check if the fall-through is also a conditional with the same merge point
    if (len(fall_through.successors) == 2 and
            _is_conditional_branch(fall_through)):
        ft_fall = fall_through.successors[0]
        ft_jump = fall_through.successors[1]

        # `and` pattern: if A fails, go to false; if A succeeds, check B
        if op == LuauOpcode.JUMPIFNOT:
            # JUMPIFNOT jumps when false -> jump_target is false path
            # fall_through is checked next
            if jump_target in (ft_fall, ft_jump):
                return "and"

        # `or` pattern: if A succeeds, go to true; if A fails, check B
        if op == LuauOpcode.JUMPIF:
            # JUMPIF jumps when true -> jump_target is true path
            if jump_target in (ft_fall, ft_jump):
                return "or"

    # Check the other direction
    if (len(jump_target.successors) == 2 and
            _is_conditional_branch(jump_target)):
        jt_fall = jump_target.successors[0]
        jt_jump = jump_target.successors[1]

        if op == LuauOpcode.JUMPIF:
            if fall_through in (jt_fall, jt_jump):
                return "and"

        if op == LuauOpcode.JUMPIFNOT:
            if fall_through in (jt_fall, jt_jump):
                return "or"

    return None


def find_conditional_exits(
    info: ConditionalInfo,
) -> Set[int]:
    """Find all block IDs that are part of this conditional structure."""
    block_ids = {info.condition_block.id}

    for b in info.then_blocks:
        block_ids.add(b.id)

    for b in info.else_blocks:
        block_ids.add(b.id)

    for cond, blocks in info.elseif_chains:
        block_ids.add(cond.id)
        for b in blocks:
            block_ids.add(b.id)

    if info.merge_block is not None:
        block_ids.add(info.merge_block.id)

    return block_ids
