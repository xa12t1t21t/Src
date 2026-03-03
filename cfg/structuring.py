"""High-level structuring from SSA/CFG to AST.

Converts a structured CFG (after loop/conditional restructuring) into
an AST Body containing properly nested statements.

This module works with the pattern matcher and restructuring passes to
emit proper Lua control flow constructs.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..function import FunctionCFG
    from ..block import BasicBlock

# Import AST types (these are being built by another agent)
try:
    from ast.src.lib import Body, Statement
    from ast.src.if_ import IfStatement
    from ast.src.while_ import WhileLoop
    from ast.src.repeat import RepeatUntil
    from ast.src.for_ import GenericFor, NumericFor
    from ast.src.break_ import Break
    from ast.src.continue_ import Continue
    from ast.src.return_ import Return
except ImportError:
    # Fallback stubs if AST package is not yet available
    class Body:
        def __init__(self):
            self.statements = []

    class Statement:
        pass


def structure_cfg(cfg: 'FunctionCFG') -> 'Body':
    """Convert a structured CFG into an AST Body.

    This is the main entry point for code generation from the CFG.
    It assumes that loops and conditionals have already been identified
    by the restructuring passes.

    Algorithm:
    1. Process blocks in reverse postorder
    2. For each block, determine if it starts a recognized pattern
    3. Emit the corresponding AST construct
    4. Skip blocks that were consumed by a pattern
    """
    from ..lib import get_blocks_in_order
    from ..pattern import (match_if_else, match_while_loop, match_for_loop,
                           match_repeat_until)

    body = Body()
    ordered_blocks = get_blocks_in_order(cfg)

    if not ordered_blocks:
        return body

    # Track which blocks have been consumed by a pattern
    consumed: Set[int] = set()

    # Process blocks
    for block in ordered_blocks:
        if block.id in consumed:
            continue

        # Try to match high-level patterns
        pattern_matched = False

        # Try for-loop first (most specific)
        for_pat = match_for_loop(cfg, block)
        if for_pat is not None:
            stmt = _emit_for_loop(cfg, for_pat, consumed)
            if stmt is not None:
                body.statements.append(stmt)
                pattern_matched = True

        # Try while loop
        if not pattern_matched:
            while_pat = match_while_loop(cfg, block)
            if while_pat is not None:
                stmt = _emit_while_loop(cfg, while_pat, consumed)
                if stmt is not None:
                    body.statements.append(stmt)
                    pattern_matched = True

        # Try repeat-until
        if not pattern_matched:
            repeat_pat = match_repeat_until(cfg, block)
            if repeat_pat is not None:
                stmt = _emit_repeat_until(cfg, repeat_pat, consumed)
                if stmt is not None:
                    body.statements.append(stmt)
                    pattern_matched = True

        # Try if-else
        if not pattern_matched:
            if_pat = match_if_else(cfg, block)
            if if_pat is not None and if_pat.then_block is not None:
                stmt = _emit_if_statement(cfg, if_pat, consumed)
                if stmt is not None:
                    body.statements.append(stmt)
                    pattern_matched = True

        # If no pattern matched, emit the block's statements directly
        if not pattern_matched:
            consumed.add(block.id)
            for stmt in block.statements:
                body.statements.append(stmt)

    return body


def _emit_block_statements(block: 'BasicBlock') -> List:
    """Get the AST statements for a single basic block."""
    return list(block.statements)


def _emit_body_for_blocks(
    cfg: 'FunctionCFG',
    blocks: List['BasicBlock'],
    consumed: Set[int],
) -> 'Body':
    """Recursively structure a sequence of blocks into a Body.

    This handles nested patterns within loop/conditional bodies.
    """
    from ..pattern import (match_if_else, match_while_loop, match_for_loop,
                           match_repeat_until)

    body = Body()

    for block in blocks:
        if block.id in consumed:
            continue

        pattern_matched = False

        # Try nested patterns
        for_pat = match_for_loop(cfg, block)
        if for_pat is not None:
            stmt = _emit_for_loop(cfg, for_pat, consumed)
            if stmt is not None:
                body.statements.append(stmt)
                pattern_matched = True

        if not pattern_matched:
            while_pat = match_while_loop(cfg, block)
            if while_pat is not None:
                stmt = _emit_while_loop(cfg, while_pat, consumed)
                if stmt is not None:
                    body.statements.append(stmt)
                    pattern_matched = True

        if not pattern_matched:
            repeat_pat = match_repeat_until(cfg, block)
            if repeat_pat is not None:
                stmt = _emit_repeat_until(cfg, repeat_pat, consumed)
                if stmt is not None:
                    body.statements.append(stmt)
                    pattern_matched = True

        if not pattern_matched:
            if_pat = match_if_else(cfg, block)
            if if_pat is not None and if_pat.then_block is not None:
                stmt = _emit_if_statement(cfg, if_pat, consumed)
                if stmt is not None:
                    body.statements.append(stmt)
                    pattern_matched = True

        if not pattern_matched:
            consumed.add(block.id)
            for stmt in block.statements:
                body.statements.append(stmt)

    return body


def _emit_if_statement(cfg, if_pat, consumed: Set[int]) -> Optional['Statement']:
    """Emit an IfStatement AST node from an IfPattern."""
    try:
        from ast.src.if_ import IfStatement
        from ast.src.lib import Body
    except ImportError:
        return None

    consumed.add(if_pat.condition_block.id)

    # Build then body
    then_blocks = [if_pat.then_block]
    consumed.add(if_pat.then_block.id)
    then_body = _emit_body_for_blocks(cfg, then_blocks, consumed)

    # Build else body
    else_body = None
    if if_pat.else_block is not None:
        else_blocks = [if_pat.else_block]
        consumed.add(if_pat.else_block.id)
        else_body = _emit_body_for_blocks(cfg, else_blocks, consumed)

    # The condition expression should be attached by the lifter
    # For now, create a placeholder
    stmt = IfStatement(
        condition=None,  # Will be filled by lifter
        then_body=then_body,
        else_body=else_body,
    )

    return stmt


def _emit_while_loop(cfg, while_pat, consumed: Set[int]) -> Optional['Statement']:
    """Emit a WhileLoop AST node from a WhilePattern."""
    try:
        from ast.src.while_ import WhileLoop
        from ast.src.lib import Body
    except ImportError:
        return None

    consumed.add(while_pat.header.id)

    # Build loop body
    body_blocks = [b for b in while_pat.body_blocks
                   if b.id != while_pat.header.id and b.id not in consumed]
    for b in body_blocks:
        consumed.add(b.id)
    loop_body = _emit_body_for_blocks(cfg, body_blocks, consumed)

    stmt = WhileLoop(
        condition=None,  # Will be filled by lifter
        body=loop_body,
    )

    return stmt


def _emit_repeat_until(cfg, repeat_pat, consumed: Set[int]) -> Optional['Statement']:
    """Emit a RepeatUntil AST node from a RepeatPattern."""
    try:
        from ast.src.repeat import RepeatUntil
        from ast.src.lib import Body
    except ImportError:
        return None

    for b in repeat_pat.body_blocks:
        consumed.add(b.id)

    body_blocks = [b for b in repeat_pat.body_blocks
                   if b.id != repeat_pat.latch.id]
    loop_body = _emit_body_for_blocks(cfg, body_blocks, consumed)

    stmt = RepeatUntil(
        condition=None,  # Will be filled by lifter
        body=loop_body,
    )

    return stmt


def _emit_for_loop(cfg, for_pat, consumed: Set[int]) -> Optional['Statement']:
    """Emit a NumericFor or GenericFor AST node from a ForPattern."""
    try:
        from ast.src.for_ import NumericFor, GenericFor
        from ast.src.lib import Body
    except ImportError:
        return None

    consumed.add(for_pat.prep_block.id)
    consumed.add(for_pat.loop_block.id)

    body_blocks = [b for b in for_pat.body_blocks
                   if b.id != for_pat.prep_block.id
                   and b.id != for_pat.loop_block.id
                   and b.id not in consumed]
    for b in body_blocks:
        consumed.add(b.id)
    loop_body = _emit_body_for_blocks(cfg, body_blocks, consumed)

    if for_pat.is_numeric:
        stmt = NumericFor(
            body=loop_body,
        )
    else:
        stmt = GenericFor(
            body=loop_body,
        )

    return stmt
