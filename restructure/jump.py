"""Jump resolution pass.

Converts remaining unstructured jumps in the CFG into proper
control flow statements: break, continue, or goto.

This pass runs after loop and conditional restructuring. Any jumps
that don't fit into the recognized patterns are resolved here.

In Luau:
- `break` exits the innermost loop
- `continue` skips to the next iteration (Luau extension)
- Remaining jumps may indicate complex control flow that needs gotos
  or restructuring with additional variables
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, TYPE_CHECKING

from cfg.src.lib import get_blocks_in_order
from deserializer.opcodes import LuauOpcode

if TYPE_CHECKING:
    from cfg.src.function import FunctionCFG
    from cfg.src.block import BasicBlock


@dataclass
class ResolvedJump:
    """A resolved jump: maps a block's outgoing edge to a control flow statement."""
    source_block_id: int
    target_block_id: int
    jump_type: str  # "break", "continue", "goto", "fallthrough", "return"
    # For goto: the label name
    label: Optional[str] = None


def resolve_jumps(cfg: 'FunctionCFG') -> List[ResolvedJump]:
    """Convert remaining jumps to break/continue/goto.

    Algorithm:
    1. For each block, examine its outgoing edges
    2. If an edge goes to a loop exit, emit `break`
    3. If an edge goes back to a loop header, emit `continue`
    4. If an edge is a natural fall-through, emit nothing
    5. Otherwise, emit `goto` (last resort)

    Returns a list of ResolvedJump objects describing each resolution.
    """
    resolved: List[ResolvedJump] = []

    # Build loop membership info
    loop_map = _build_loop_membership(cfg)

    # Get the set of blocks that are loop headers and their exit blocks
    loop_exits = _build_loop_exit_map(cfg)
    loop_headers = _get_loop_header_ids(cfg)

    ordered_blocks = get_blocks_in_order(cfg)
    block_order = {b.id: idx for idx, b in enumerate(ordered_blocks)}

    for block in cfg.blocks:
        if not block.instructions:
            continue

        last_insn = block.instructions[-1]
        try:
            opcode = LuauOpcode(last_insn.opcode)
        except ValueError:
            continue

        # Only process explicit jumps
        jump_opcodes = {
            LuauOpcode.JUMP, LuauOpcode.JUMPBACK, LuauOpcode.JUMPX,
            LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT,
            LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
            LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE,
            LuauOpcode.JUMPIFNOTLT,
            LuauOpcode.JUMPXEQKNIL, LuauOpcode.JUMPXEQKB,
            LuauOpcode.JUMPXEQKN, LuauOpcode.JUMPXEQKS,
        }

        if opcode not in jump_opcodes:
            if opcode == LuauOpcode.RETURN:
                resolved.append(ResolvedJump(
                    source_block_id=block.id,
                    target_block_id=-1,
                    jump_type="return",
                ))
            continue

        # Resolve each successor edge
        for succ in block.successors:
            jump_type = _classify_jump(
                block, succ, loop_map, loop_exits, loop_headers, block_order
            )
            label = None
            if jump_type == "goto":
                label = f"label_B{succ.id}"

            resolved.append(ResolvedJump(
                source_block_id=block.id,
                target_block_id=succ.id,
                jump_type=jump_type,
                label=label,
            ))

    # Store on CFG
    if not hasattr(cfg, 'resolved_jumps'):
        cfg.resolved_jumps = []
    cfg.resolved_jumps = resolved

    return resolved


def _classify_jump(
    source: 'BasicBlock',
    target: 'BasicBlock',
    loop_map: Dict[int, Set[int]],
    loop_exits: Dict[int, int],
    loop_headers: Set[int],
    block_order: Dict[int, int],
) -> str:
    """Classify a jump edge as break, continue, goto, or fallthrough."""

    # Check if this is a fallthrough (next block in order)
    source_order = block_order.get(source.id, -1)
    target_order = block_order.get(target.id, -1)
    if target_order == source_order + 1:
        return "fallthrough"

    # Check if the source is inside a loop
    containing_loops = _get_containing_loops(source.id, loop_map)

    if containing_loops:
        for loop_header_id in containing_loops:
            # Check if target is the loop exit -> break
            exit_id = loop_exits.get(loop_header_id)
            if exit_id is not None and target.id == exit_id:
                return "break"

            # Check if target is the loop header -> continue
            if target.id == loop_header_id:
                # Only if this is not the latch (natural loop back-edge)
                if not source.is_loop_latch:
                    return "continue"
                else:
                    return "fallthrough"  # natural back-edge

    # Check if target is a loop header we're jumping into (back edge)
    if target.id in loop_headers and target.start_pc <= source.start_pc:
        return "continue"

    # Default: goto
    return "goto"


def _build_loop_membership(cfg: 'FunctionCFG') -> Dict[int, Set[int]]:
    """Build a map from loop header ID to set of block IDs in the loop.

    Returns a dict mapping loop_header_id -> set of member block IDs.
    """
    loop_map: Dict[int, Set[int]] = {}

    if hasattr(cfg, 'loops'):
        for loop_info in cfg.loops:
            loop_map[loop_info.header.id] = loop_info.body_block_ids
    else:
        # Fall back to basic back-edge detection
        from cfg.src.lib import find_loops, get_loop_body
        for header, latch in find_loops(cfg):
            body = get_loop_body(cfg, header, latch)
            loop_map[header.id] = {b.id for b in body}

    return loop_map


def _build_loop_exit_map(cfg: 'FunctionCFG') -> Dict[int, int]:
    """Build a map from loop header ID to exit block ID."""
    exit_map: Dict[int, int] = {}

    if hasattr(cfg, 'loops'):
        for loop_info in cfg.loops:
            if loop_info.exit_block is not None:
                exit_map[loop_info.header.id] = loop_info.exit_block.id

    return exit_map


def _get_loop_header_ids(cfg: 'FunctionCFG') -> Set[int]:
    """Get the set of all loop header block IDs."""
    headers = set()
    for block in cfg.blocks:
        if block.is_loop_header:
            headers.add(block.id)
    return headers


def _get_containing_loops(
    block_id: int,
    loop_map: Dict[int, Set[int]],
) -> List[int]:
    """Get the list of loop header IDs for loops containing the given block.

    Returns loops ordered from innermost to outermost.
    """
    containing = []
    for header_id, members in loop_map.items():
        if block_id in members:
            containing.append((header_id, len(members)))

    # Sort by size (smallest = innermost first)
    containing.sort(key=lambda x: x[1])
    return [h for h, _ in containing]


def insert_break_continue_statements(cfg: 'FunctionCFG'):
    """Insert Break and Continue AST statements into appropriate blocks.

    This should be called after resolve_jumps() to actually create the
    AST nodes.
    """
    try:
        from ast.src.break_ import Break
        from ast.src.continue_ import Continue
    except ImportError:
        return

    if not hasattr(cfg, 'resolved_jumps'):
        return

    for jump in cfg.resolved_jumps:
        block = cfg.get_block_by_id(jump.source_block_id)
        if block is None:
            continue

        if jump.jump_type == "break":
            block.statements.append(Break())
        elif jump.jump_type == "continue":
            block.statements.append(Continue())
        # goto and fallthrough are handled elsewhere
