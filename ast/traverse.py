"""AST traversal utilities.

Provides generators for walking AST nodes, yielding statements
and/or expressions encountered during traversal.
"""

from typing import Generator
from .lib import ASTNode, Body, Expression, Statement
from .literal import NumberLiteral, StringLiteral, BoolLiteral, NilLiteral
from .local import LocalRef
from .global_ref import GlobalRef
from .binary import BinaryOp
from .unary import UnaryOp
from .call import FunctionCall, MethodCall, FunctionCallStatement
from .table import TableConstructor
from .index import IndexExpression, DotExpression
from .closure import Closure
from .vararg import VarargExpression
from .local_declarations import LocalDeclaration
from .assign import Assignment
from .return_ import Return
from .for_ import GenericFor, NumericFor
from .if_ import IfStatement
from .while_ import WhileLoop
from .repeat import RepeatUntil
from .break_ import Break
from .continue_ import Continue
from .goto import Goto, Label
from .close import CloseUpvalues
from .set_list import SetList


def walk(node: ASTNode) -> Generator[ASTNode, None, None]:
    """Walk the AST tree, yielding all nodes (both statements and expressions).

    Performs a depth-first traversal.
    """
    yield node

    if isinstance(node, Body):
        for stmt in node.statements:
            yield from walk(stmt)

    elif isinstance(node, Statement):
        yield from _walk_statement_children(node)

    elif isinstance(node, Expression):
        yield from _walk_expression_children(node)


def walk_statements(body: Body) -> Generator[Statement, None, None]:
    """Walk all statements in a body, recursively entering sub-bodies.

    Yields only Statement nodes.
    """
    for stmt in body.statements:
        yield stmt
        yield from _walk_sub_statements(stmt)


def _walk_sub_statements(stmt: Statement) -> Generator[Statement, None, None]:
    """Yield all statements nested within a given statement."""
    if isinstance(stmt, GenericFor):
        yield from walk_statements(stmt.body)

    elif isinstance(stmt, NumericFor):
        yield from walk_statements(stmt.body)

    elif isinstance(stmt, IfStatement):
        yield from walk_statements(stmt.then_body)
        for _, elseif_body in stmt.elseif_clauses:
            yield from walk_statements(elseif_body)
        if stmt.else_body is not None:
            yield from walk_statements(stmt.else_body)

    elif isinstance(stmt, WhileLoop):
        yield from walk_statements(stmt.body)

    elif isinstance(stmt, RepeatUntil):
        yield from walk_statements(stmt.body)

    # Also recurse into closures found in expressions within this statement
    for expr in _walk_statement_expressions(stmt):
        if isinstance(expr, Closure):
            yield from walk_statements(expr.body)


def walk_expressions(body: Body) -> Generator[Expression, None, None]:
    """Walk all expressions in a body, recursively.

    Yields only Expression nodes.
    """
    for stmt in body.statements:
        yield from _walk_statement_expressions(stmt)
        # Recurse into sub-bodies
        if isinstance(stmt, GenericFor):
            yield from walk_expressions(stmt.body)
        elif isinstance(stmt, NumericFor):
            yield from walk_expressions(stmt.body)
        elif isinstance(stmt, IfStatement):
            yield from walk_expressions(stmt.then_body)
            for _, elseif_body in stmt.elseif_clauses:
                yield from walk_expressions(elseif_body)
            if stmt.else_body is not None:
                yield from walk_expressions(stmt.else_body)
        elif isinstance(stmt, WhileLoop):
            yield from walk_expressions(stmt.body)
        elif isinstance(stmt, RepeatUntil):
            yield from walk_expressions(stmt.body)


def _walk_statement_expressions(stmt: Statement) -> Generator[Expression, None, None]:
    """Yield all direct expressions within a statement (not recursing into sub-bodies)."""
    if isinstance(stmt, LocalDeclaration):
        for val in stmt.values:
            yield from _walk_expr_tree(val)

    elif isinstance(stmt, Assignment):
        for target in stmt.targets:
            yield from _walk_expr_tree(target)
        for val in stmt.values:
            yield from _walk_expr_tree(val)

    elif isinstance(stmt, FunctionCallStatement):
        if stmt.call is not None:
            yield from _walk_expr_tree(stmt.call)

    elif isinstance(stmt, Return):
        for val in stmt.values:
            yield from _walk_expr_tree(val)

    elif isinstance(stmt, GenericFor):
        for it in stmt.iterators:
            yield from _walk_expr_tree(it)

    elif isinstance(stmt, NumericFor):
        if stmt.start is not None:
            yield from _walk_expr_tree(stmt.start)
        if stmt.stop is not None:
            yield from _walk_expr_tree(stmt.stop)
        if stmt.step is not None:
            yield from _walk_expr_tree(stmt.step)

    elif isinstance(stmt, IfStatement):
        if stmt.condition is not None:
            yield from _walk_expr_tree(stmt.condition)
        for cond, _ in stmt.elseif_clauses:
            yield from _walk_expr_tree(cond)

    elif isinstance(stmt, WhileLoop):
        if stmt.condition is not None:
            yield from _walk_expr_tree(stmt.condition)

    elif isinstance(stmt, RepeatUntil):
        if stmt.condition is not None:
            yield from _walk_expr_tree(stmt.condition)

    elif isinstance(stmt, SetList):
        if stmt.table is not None:
            yield from _walk_expr_tree(stmt.table)
        for val in stmt.values:
            yield from _walk_expr_tree(val)


def _walk_expr_tree(expr: Expression) -> Generator[Expression, None, None]:
    """Walk an expression tree, yielding all expressions depth-first."""
    if expr is None:
        return

    yield expr

    if isinstance(expr, BinaryOp):
        if expr.left is not None:
            yield from _walk_expr_tree(expr.left)
        if expr.right is not None:
            yield from _walk_expr_tree(expr.right)

    elif isinstance(expr, UnaryOp):
        if expr.operand is not None:
            yield from _walk_expr_tree(expr.operand)

    elif isinstance(expr, FunctionCall):
        if expr.func is not None:
            yield from _walk_expr_tree(expr.func)
        for arg in expr.args:
            yield from _walk_expr_tree(arg)

    elif isinstance(expr, MethodCall):
        if expr.object is not None:
            yield from _walk_expr_tree(expr.object)
        for arg in expr.args:
            yield from _walk_expr_tree(arg)

    elif isinstance(expr, TableConstructor):
        for f in expr.fields:
            if f.key is not None:
                yield from _walk_expr_tree(f.key)
            if f.value is not None:
                yield from _walk_expr_tree(f.value)

    elif isinstance(expr, IndexExpression):
        if expr.table is not None:
            yield from _walk_expr_tree(expr.table)
        if expr.key is not None:
            yield from _walk_expr_tree(expr.key)

    elif isinstance(expr, DotExpression):
        if expr.table is not None:
            yield from _walk_expr_tree(expr.table)

    elif isinstance(expr, Closure):
        # Walk the closure body expressions
        yield from walk_expressions(expr.body)


def _walk_statement_children(stmt: Statement) -> Generator[ASTNode, None, None]:
    """Yield all children of a statement node."""
    # Yield expressions
    for expr in _walk_statement_expressions(stmt):
        yield expr

    # Yield sub-body statements
    if isinstance(stmt, GenericFor):
        for s in stmt.body.statements:
            yield from walk(s)
    elif isinstance(stmt, NumericFor):
        for s in stmt.body.statements:
            yield from walk(s)
    elif isinstance(stmt, IfStatement):
        for s in stmt.then_body.statements:
            yield from walk(s)
        for _, elseif_body in stmt.elseif_clauses:
            for s in elseif_body.statements:
                yield from walk(s)
        if stmt.else_body is not None:
            for s in stmt.else_body.statements:
                yield from walk(s)
    elif isinstance(stmt, WhileLoop):
        for s in stmt.body.statements:
            yield from walk(s)
    elif isinstance(stmt, RepeatUntil):
        for s in stmt.body.statements:
            yield from walk(s)


def _walk_expression_children(expr: Expression) -> Generator[ASTNode, None, None]:
    """Yield all children of an expression node."""
    if isinstance(expr, BinaryOp):
        if expr.left is not None:
            yield from walk(expr.left)
        if expr.right is not None:
            yield from walk(expr.right)

    elif isinstance(expr, UnaryOp):
        if expr.operand is not None:
            yield from walk(expr.operand)

    elif isinstance(expr, FunctionCall):
        if expr.func is not None:
            yield from walk(expr.func)
        for arg in expr.args:
            yield from walk(arg)

    elif isinstance(expr, MethodCall):
        if expr.object is not None:
            yield from walk(expr.object)
        for arg in expr.args:
            yield from walk(arg)

    elif isinstance(expr, TableConstructor):
        for f in expr.fields:
            if f.key is not None:
                yield from walk(f.key)
            if f.value is not None:
                yield from walk(f.value)

    elif isinstance(expr, IndexExpression):
        if expr.table is not None:
            yield from walk(expr.table)
        if expr.key is not None:
            yield from walk(expr.key)

    elif isinstance(expr, DotExpression):
        if expr.table is not None:
            yield from walk(expr.table)

    elif isinstance(expr, Closure):
        for s in expr.body.statements:
            yield from walk(s)
