"""Side effect analysis for AST nodes.

This module provides utilities for determining whether an expression or
statement has side effects. This is important for optimization passes
in the decompiler, such as:

- Dead code elimination: expressions without side effects can be removed
  if their result is unused.
- Expression reordering: expressions without side effects can be safely
  reordered without changing program semantics.
- Inlining decisions: side-effect-free expressions can be duplicated
  or moved without affecting correctness.

Side effects include:
- Function calls (may modify global state)
- Assignments to globals or table fields
- Mutations through method calls

Pure expressions (no side effects):
- Literal values (numbers, strings, booleans, nil)
- Local variable references
- Table constructors with pure field expressions
- Arithmetic/comparison operations on pure operands
"""

from .lib import ASTNode, Expression
from .literal import NumberLiteral, StringLiteral, BoolLiteral, NilLiteral
from .local import LocalRef
from .global_ref import GlobalRef
from .binary import BinaryOp
from .unary import UnaryOp
from .vararg import VarargExpression
from .table import TableConstructor
from .call import FunctionCall, MethodCall


def has_side_effects(node: Expression) -> bool:
    """Determine whether an expression may have side effects.

    Returns True if the expression may modify program state,
    False if it is guaranteed to be pure.
    """
    if isinstance(node, (NumberLiteral, StringLiteral, BoolLiteral, NilLiteral)):
        return False

    if isinstance(node, LocalRef):
        return False

    if isinstance(node, GlobalRef):
        # Global reads are technically side-effect-free, but the value
        # could change between reads. For now, treat as pure.
        return False

    if isinstance(node, VarargExpression):
        return False

    if isinstance(node, BinaryOp):
        return has_side_effects(node.left) or has_side_effects(node.right)

    if isinstance(node, UnaryOp):
        return has_side_effects(node.operand)

    if isinstance(node, TableConstructor):
        for f in node.fields:
            if f.key is not None and has_side_effects(f.key):
                return True
            if has_side_effects(f.value):
                return True
        return False

    if isinstance(node, (FunctionCall, MethodCall)):
        return True

    # Unknown node type - assume side effects for safety
    return True
