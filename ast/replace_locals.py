"""Utility for replacing Local references throughout an AST.

This is useful for SSA deconstruction, variable merging, and other
transformations where one local variable needs to be substituted
with another.
"""

from .lib import Body, ASTNode, Expression, Statement
from .local import Local, LocalRef
from .local_declarations import LocalDeclaration
from .for_ import GenericFor, NumericFor
from .closure import Closure
from .call import FunctionCall, MethodCall, FunctionCallStatement
from .assign import Assignment
from .return_ import Return
from .binary import BinaryOp
from .unary import UnaryOp
from .table import TableConstructor
from .index import IndexExpression, DotExpression
from .if_ import IfStatement
from .while_ import WhileLoop
from .repeat import RepeatUntil
from .set_list import SetList


def replace_local(body: Body, old: Local, new: Local):
    """Replace all occurrences of `old` local with `new` local in the body.

    This modifies the AST in place. It replaces:
    - LocalRef references pointing to old
    - Local declarations that declare old
    - For loop variables that are old
    - Closure parameters that are old

    Args:
        body: The AST body to transform.
        old: The Local object to replace.
        new: The Local object to replace it with.
    """
    _replace_in_body(body, old, new)


def _replace_in_body(body: Body, old: Local, new: Local):
    """Replace locals in all statements in a body."""
    for stmt in body.statements:
        _replace_in_statement(stmt, old, new)


def _replace_in_statement(stmt: Statement, old: Local, new: Local):
    """Replace locals in a single statement."""
    if isinstance(stmt, LocalDeclaration):
        for i, local in enumerate(stmt.locals):
            if local is old:
                stmt.locals[i] = new
        _replace_in_expression_list(stmt.values, old, new)

    elif isinstance(stmt, Assignment):
        _replace_in_expression_list(stmt.targets, old, new)
        _replace_in_expression_list(stmt.values, old, new)

    elif isinstance(stmt, FunctionCallStatement):
        if stmt.call is not None:
            replaced = _replace_in_expression(stmt.call, old, new)
            if replaced is not stmt.call:
                stmt.call = replaced

    elif isinstance(stmt, Return):
        _replace_in_expression_list(stmt.values, old, new)

    elif isinstance(stmt, GenericFor):
        for i, var in enumerate(stmt.vars):
            if var is old:
                stmt.vars[i] = new
        _replace_in_expression_list(stmt.iterators, old, new)
        _replace_in_body(stmt.body, old, new)

    elif isinstance(stmt, NumericFor):
        if stmt.var is old:
            stmt.var = new
        if stmt.start is not None:
            replaced = _replace_in_expression(stmt.start, old, new)
            if replaced is not stmt.start:
                stmt.start = replaced
        if stmt.stop is not None:
            replaced = _replace_in_expression(stmt.stop, old, new)
            if replaced is not stmt.stop:
                stmt.stop = replaced
        if stmt.step is not None:
            replaced = _replace_in_expression(stmt.step, old, new)
            if replaced is not stmt.step:
                stmt.step = replaced
        _replace_in_body(stmt.body, old, new)

    elif isinstance(stmt, IfStatement):
        if stmt.condition is not None:
            replaced = _replace_in_expression(stmt.condition, old, new)
            if replaced is not stmt.condition:
                stmt.condition = replaced
        _replace_in_body(stmt.then_body, old, new)
        for i, (cond, elseif_body) in enumerate(stmt.elseif_clauses):
            replaced = _replace_in_expression(cond, old, new)
            if replaced is not cond:
                stmt.elseif_clauses[i] = (replaced, elseif_body)
            _replace_in_body(elseif_body, old, new)
        if stmt.else_body is not None:
            _replace_in_body(stmt.else_body, old, new)

    elif isinstance(stmt, WhileLoop):
        if stmt.condition is not None:
            replaced = _replace_in_expression(stmt.condition, old, new)
            if replaced is not stmt.condition:
                stmt.condition = replaced
        _replace_in_body(stmt.body, old, new)

    elif isinstance(stmt, RepeatUntil):
        if stmt.condition is not None:
            replaced = _replace_in_expression(stmt.condition, old, new)
            if replaced is not stmt.condition:
                stmt.condition = replaced
        _replace_in_body(stmt.body, old, new)

    elif isinstance(stmt, SetList):
        if stmt.table is not None:
            replaced = _replace_in_expression(stmt.table, old, new)
            if replaced is not stmt.table:
                stmt.table = replaced
        _replace_in_expression_list(stmt.values, old, new)


def _replace_in_expression(expr: Expression, old: Local, new: Local) -> Expression:
    """Replace locals in an expression. Returns the (possibly new) expression."""
    if isinstance(expr, LocalRef):
        if expr.local is old:
            expr.local = new
        return expr

    elif isinstance(expr, BinaryOp):
        if expr.left is not None:
            expr.left = _replace_in_expression(expr.left, old, new)
        if expr.right is not None:
            expr.right = _replace_in_expression(expr.right, old, new)
        return expr

    elif isinstance(expr, UnaryOp):
        if expr.operand is not None:
            expr.operand = _replace_in_expression(expr.operand, old, new)
        return expr

    elif isinstance(expr, FunctionCall):
        if expr.func is not None:
            expr.func = _replace_in_expression(expr.func, old, new)
        _replace_in_expression_list(expr.args, old, new)
        return expr

    elif isinstance(expr, MethodCall):
        if expr.object is not None:
            expr.object = _replace_in_expression(expr.object, old, new)
        _replace_in_expression_list(expr.args, old, new)
        return expr

    elif isinstance(expr, TableConstructor):
        for f in expr.fields:
            if f.key is not None:
                f.key = _replace_in_expression(f.key, old, new)
            if f.value is not None:
                f.value = _replace_in_expression(f.value, old, new)
        return expr

    elif isinstance(expr, IndexExpression):
        if expr.table is not None:
            expr.table = _replace_in_expression(expr.table, old, new)
        if expr.key is not None:
            expr.key = _replace_in_expression(expr.key, old, new)
        return expr

    elif isinstance(expr, DotExpression):
        if expr.table is not None:
            expr.table = _replace_in_expression(expr.table, old, new)
        return expr

    elif isinstance(expr, Closure):
        for i, param in enumerate(expr.params):
            if param is old:
                expr.params[i] = new
        _replace_in_body(expr.body, old, new)
        return expr

    return expr


def _replace_in_expression_list(exprs: list, old: Local, new: Local):
    """Replace locals in a list of expressions, modifying the list in place."""
    for i, expr in enumerate(exprs):
        if expr is not None:
            replaced = _replace_in_expression(expr, old, new)
            if replaced is not expr:
                exprs[i] = replaced
