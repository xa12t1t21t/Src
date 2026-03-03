"""AST to Lua source code formatter.

This module converts an AST back into valid Lua source code text.
It handles indentation, operator precedence, string escaping,
and all Lua syntax constructs.
"""

import re
from typing import List, Optional, Tuple

from .lib import Body, Expression, Statement, ASTNode
from .literal import NumberLiteral, StringLiteral, BoolLiteral, NilLiteral
from .local import Local, LocalRef
from .global_ref import GlobalRef
from .table import TableConstructor, TableField
from .call import FunctionCall, MethodCall, FunctionCallStatement
from .for_ import GenericFor, NumericFor
from .assign import Assignment
from .local_declarations import LocalDeclaration
from .return_ import Return
from .binary import BinaryOp
from .unary import UnaryOp
from .index import IndexExpression, DotExpression
from .closure import Closure
from .if_ import IfStatement
from .while_ import WhileLoop
from .repeat import RepeatUntil
from .break_ import Break
from .continue_ import Continue
from .goto import Goto, Label
from .vararg import VarargExpression
from .close import CloseUpvalues
from .set_list import SetList


# Lua identifier pattern
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

# Lua reserved keywords (cannot be used as bare identifiers in table keys)
_RESERVED_KEYWORDS = frozenset({
    "and", "break", "do", "else", "elseif", "end",
    "false", "for", "function", "goto", "if", "in",
    "local", "nil", "not", "or", "repeat", "return",
    "then", "true", "until", "while",
    "continue", "type", "export",
})

# Operator precedence table for Lua (higher = binds tighter)
_PRECEDENCE = {
    "or": 1,
    "and": 2,
    "<": 3, ">": 3, "<=": 3, ">=": 3, "~=": 3, "==": 3,
    "..": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "//": 6, "%": 6,
    # Unary operators (not, #, - (unary)) have precedence 7
    "^": 8,
}

# Right-associative operators
_RIGHT_ASSOC = {"^", ".."}

INDENT = "    "


def _is_valid_identifier(name: str) -> bool:
    """Check if a string is a valid Lua identifier (and not a reserved keyword)."""
    return bool(_IDENT_RE.match(name)) and name not in _RESERVED_KEYWORDS


def _escape_string(s: str) -> str:
    """Escape a string for Lua string literal output."""
    result = []
    for ch in s:
        if ch == '\\':
            result.append('\\\\')
        elif ch == '"':
            result.append('\\"')
        elif ch == '\n':
            result.append('\\n')
        elif ch == '\r':
            result.append('\\r')
        elif ch == '\t':
            result.append('\\t')
        elif ch == '\0':
            result.append('\\0')
        elif ch == '\a':
            result.append('\\a')
        elif ch == '\b':
            result.append('\\b')
        elif ch == '\f':
            result.append('\\f')
        elif ch == '\v':
            result.append('\\v')
        elif ord(ch) < 32 or ord(ch) == 127:
            result.append(f'\\{ord(ch)}')
        else:
            result.append(ch)
    return '"' + ''.join(result) + '"'


def _format_number(value: float) -> str:
    """Format a number for Lua output.

    Integers (like 1.0) are printed as "1", not "1.0".
    """
    if value != value:  # NaN
        return "0/0"
    if value == float('inf'):
        return "1/0"
    if value == float('-inf'):
        return "-1/0"
    # Check if it's an integer value
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value)


def _get_precedence(op: str) -> int:
    """Get the precedence of a binary operator."""
    return _PRECEDENCE.get(op, 0)


def _needs_parens_left(parent_op: str, child: Expression) -> bool:
    """Check if the left child of a binary op needs parentheses."""
    if not isinstance(child, BinaryOp):
        return False
    parent_prec = _get_precedence(parent_op)
    child_prec = _get_precedence(child.op)
    if child_prec < parent_prec:
        return True
    return False


def _needs_parens_right(parent_op: str, child: Expression) -> bool:
    """Check if the right child of a binary op needs parentheses."""
    if not isinstance(child, BinaryOp):
        return False
    parent_prec = _get_precedence(parent_op)
    child_prec = _get_precedence(child.op)
    if child_prec < parent_prec:
        return True
    # For left-associative operators with equal precedence on the right side,
    # we need parens: (a - b) - c is fine, but a - (b - c) needs parens
    if child_prec == parent_prec and parent_op not in _RIGHT_ASSOC:
        return True
    return False


def format_body(body: Body, indent: int = 0) -> str:
    """Format a Body (list of statements) into Lua source code.

    Args:
        body: The Body to format.
        indent: Current indentation level.

    Returns:
        Formatted Lua source code string.
    """
    lines = []
    for i, stmt in enumerate(body.statements):
        # Skip CloseUpvalues -- internal bytecode op, not real Lua syntax
        if isinstance(stmt, CloseUpvalues):
            continue
        # Skip SetList -- internal bytecode op, handled by table constructors
        if isinstance(stmt, SetList):
            continue
        # At indent 0 (top level), skip empty returns (return with no values)
        if indent == 0 and isinstance(stmt, Return) and len(stmt.values) == 0:
            continue
        formatted = format_statement(stmt, indent)
        if formatted is not None:
            lines.append(formatted)
        # After a terminating statement, remaining statements are unreachable dead
        # code that would cause syntax errors (Luau forbids statements after return/
        # break/continue/goto in the same block).
        if isinstance(stmt, (Return, Break, Continue, Goto)):
            break
    return "\n".join(lines)


def format_statement(stmt: Statement, indent: int = 0) -> Optional[str]:
    """Format a single statement into a Lua source line.

    Args:
        stmt: The Statement to format.
        indent: Current indentation level.

    Returns:
        Formatted string, or None if the statement should be skipped.
    """
    prefix = INDENT * indent

    if isinstance(stmt, LocalDeclaration):
        names = ", ".join(local.name or "_" for local in stmt.locals)
        if stmt.values:
            values = ", ".join(format_expression(v, indent) for v in stmt.values)
            return f"{prefix}local {names} = {values};"
        else:
            return f"{prefix}local {names};"

    elif isinstance(stmt, FunctionCallStatement):
        if stmt.call is not None:
            return f"{prefix}{format_expression(stmt.call, indent)};"
        return None

    elif isinstance(stmt, Assignment):
        targets = ", ".join(format_expression(t, indent) for t in stmt.targets)
        values = ", ".join(format_expression(v, indent) for v in stmt.values)
        return f"{prefix}{targets} = {values};"

    elif isinstance(stmt, Return):
        if stmt.values:
            values = ", ".join(format_expression(v, indent) for v in stmt.values)
            return f"{prefix}return {values};"
        else:
            return f"{prefix}return;"

    elif isinstance(stmt, GenericFor):
        var_names = ", ".join(v.name or "_" for v in stmt.vars)
        iterators = ", ".join(format_expression(e, indent) for e in stmt.iterators)
        body_str = format_body(stmt.body, indent + 1)
        result = f"{prefix}for {var_names} in {iterators} do\n"
        if body_str:
            result += body_str + "\n"
        result += f"{prefix}end"
        return result

    elif isinstance(stmt, NumericFor):
        var_name = stmt.var.name or "_"
        start = format_expression(stmt.start, indent) if stmt.start else "0"
        stop = format_expression(stmt.stop, indent) if stmt.stop else "0"
        if stmt.step is not None:
            step = format_expression(stmt.step, indent)
            header = f"{prefix}for {var_name} = {start}, {stop}, {step} do\n"
        else:
            header = f"{prefix}for {var_name} = {start}, {stop} do\n"
        body_str = format_body(stmt.body, indent + 1)
        result = header
        if body_str:
            result += body_str + "\n"
        result += f"{prefix}end"
        return result

    elif isinstance(stmt, IfStatement):
        cond = format_expression(stmt.condition, indent) if stmt.condition else "true"
        result = f"{prefix}if {cond} then\n"
        body_str = format_body(stmt.then_body, indent + 1)
        if body_str:
            result += body_str + "\n"

        for elseif_cond, elseif_body in stmt.elseif_clauses:
            ec = format_expression(elseif_cond, indent)
            result += f"{prefix}elseif {ec} then\n"
            eb_str = format_body(elseif_body, indent + 1)
            if eb_str:
                result += eb_str + "\n"

        if stmt.else_body is not None:
            result += f"{prefix}else\n"
            else_str = format_body(stmt.else_body, indent + 1)
            if else_str:
                result += else_str + "\n"

        result += f"{prefix}end"
        return result

    elif isinstance(stmt, WhileLoop):
        cond = format_expression(stmt.condition, indent) if stmt.condition else "true"
        body_str = format_body(stmt.body, indent + 1)
        result = f"{prefix}while {cond} do\n"
        if body_str:
            result += body_str + "\n"
        result += f"{prefix}end"
        return result

    elif isinstance(stmt, RepeatUntil):
        body_str = format_body(stmt.body, indent + 1)
        cond = format_expression(stmt.condition, indent) if stmt.condition else "false"
        result = f"{prefix}repeat\n"
        if body_str:
            result += body_str + "\n"
        result += f"{prefix}until {cond}"
        return result

    elif isinstance(stmt, Break):
        return f"{prefix}break;"

    elif isinstance(stmt, Continue):
        return f"{prefix}continue;"

    elif isinstance(stmt, Goto):
        return f"{prefix}goto {stmt.label};"

    elif isinstance(stmt, Label):
        return f"{prefix}::{stmt.name}::"

    elif isinstance(stmt, CloseUpvalues):
        # Internal operation, skip in output
        return None

    elif isinstance(stmt, SetList):
        # Internal operation, skip in output
        return None

    else:
        # Unknown statement type - output as comment
        return f"{prefix}-- unknown statement: {type(stmt).__name__}"


def format_expression(expr: Expression, indent: int = 0) -> str:
    """Format an expression into a Lua source string.

    Args:
        expr: The Expression to format.
        indent: Current indentation level (used for closures and tables).

    Returns:
        Formatted Lua expression string.
    """
    if expr is None:
        return "nil"

    if isinstance(expr, NumberLiteral):
        return _format_number(expr.value)

    elif isinstance(expr, StringLiteral):
        return _escape_string(expr.value)

    elif isinstance(expr, BoolLiteral):
        return "true" if expr.value else "false"

    elif isinstance(expr, NilLiteral):
        return "nil"

    elif isinstance(expr, LocalRef):
        return expr.local.name or "_"

    elif isinstance(expr, GlobalRef):
        return expr.name

    elif isinstance(expr, VarargExpression):
        return "..."

    elif isinstance(expr, TableConstructor):
        return _format_table_constructor(expr, indent)

    elif isinstance(expr, FunctionCall):
        func_str = format_expression(expr.func, indent)
        # Wrap complex expressions in parens when calling
        if isinstance(expr.func, (Closure, BinaryOp, UnaryOp, VarargExpression)):
            func_str = f"({func_str})"
        args = ", ".join(format_expression(a, indent) for a in expr.args)
        return f"{func_str}({args})"

    elif isinstance(expr, MethodCall):
        obj_str = format_expression(expr.object, indent)
        args = ", ".join(format_expression(a, indent) for a in expr.args)
        return f"{obj_str}:{expr.method}({args})"

    elif isinstance(expr, BinaryOp):
        return _format_binary_op(expr, indent)

    elif isinstance(expr, UnaryOp):
        return _format_unary_op(expr, indent)

    elif isinstance(expr, IndexExpression):
        table_str = format_expression(expr.table, indent)
        # Literals can't be indexed without parens: nil[k] and 1[k] are syntax errors
        if isinstance(expr.table, (NilLiteral, BoolLiteral, NumberLiteral)):
            table_str = f"({table_str})"
        key_str = format_expression(expr.key, indent)
        return f"{table_str}[{key_str}]"

    elif isinstance(expr, DotExpression):
        table_str = format_expression(expr.table, indent)
        # nil.field and true.field are syntax errors without parens
        if isinstance(expr.table, (NilLiteral, BoolLiteral, NumberLiteral)):
            table_str = f"({table_str})"
        return f"{table_str}.{expr.field_name}"

    elif isinstance(expr, Closure):
        return _format_closure(expr, indent=indent)

    else:
        return f"--[[ unknown expr: {type(expr).__name__} ]]"


def _format_table_constructor(table: TableConstructor, indent: int = 0) -> str:
    """Format a table constructor expression."""
    if not table.fields:
        return "{}"

    parts = []
    for f in table.fields:
        if f.key is None:
            # Array part: just the value
            parts.append(format_expression(f.value, indent + 1))
        elif isinstance(f.key, StringLiteral) and _is_valid_identifier(f.key.value):
            # String key that is a valid identifier: key = value
            parts.append(f"{f.key.value} = {format_expression(f.value, indent + 1)}")
        else:
            # General key: [key] = value
            parts.append(f"[{format_expression(f.key, indent + 1)}] = {format_expression(f.value, indent + 1)}")

    # Use single-line format for short tables, multi-line for longer ones
    single_line = "{" + ", ".join(parts) + "}"
    if len(single_line) <= 80 and "\n" not in single_line:
        return single_line

    # Multi-line format
    inner = ",\n".join((INDENT * (indent + 1)) + p for p in parts)
    return "{\n" + inner + "\n" + (INDENT * indent) + "}"


def _format_binary_op(expr: BinaryOp, indent: int = 0) -> str:
    """Format a binary operation with proper precedence parentheses."""
    left_str = format_expression(expr.left, indent)
    right_str = format_expression(expr.right, indent)

    # Add parentheses to left operand if needed
    if _needs_parens_left(expr.op, expr.left):
        left_str = f"({left_str})"

    # Add parentheses to right operand if needed
    if _needs_parens_right(expr.op, expr.right):
        right_str = f"({right_str})"

    # Also parenthesize unary on left of certain operators to avoid ambiguity
    # e.g., (-a) ^ b  (unary minus has lower precedence than ^)
    if isinstance(expr.left, UnaryOp) and _get_precedence(expr.op) > 7:
        left_str = f"({format_expression(expr.left, indent)})"

    return f"{left_str} {expr.op} {right_str}"


def _format_unary_op(expr: UnaryOp, indent: int = 0) -> str:
    """Format a unary operation."""
    operand_str = format_expression(expr.operand, indent)

    # Parenthesize binary ops inside unary
    if isinstance(expr.operand, BinaryOp):
        operand_str = f"({operand_str})"

    if expr.op == "not":
        return f"not {operand_str}"
    elif expr.op == "#":
        return f"#{operand_str}"
    elif expr.op == "-":
        # Avoid -- which would be a comment
        if operand_str.startswith("-"):
            return f"-({operand_str})"
        return f"-{operand_str}"
    else:
        return f"{expr.op}{operand_str}"


def _format_closure(closure: Closure, indent: int = 0) -> str:
    """Format a closure/function expression."""
    param_names = [p.name or "_" for p in closure.params]
    if closure.is_vararg:
        param_names.append("...")
    params_str = ", ".join(param_names)

    # Check for line number and debug name annotations
    debug_name = getattr(closure, 'debug_name', None)
    line_defined = getattr(closure, 'line_defined', None)
    line_annotation = f" --[[ Line: {line_defined} ]]" if line_defined else ""
    name_annotation = f" --[[ Name: {debug_name} ]]" if debug_name else ""

    # Check for upvalue captures comment
    upvalue_captures = getattr(closure, 'upvalue_captures', None)
    inner_prefix = INDENT * (indent + 1)
    upval_comment = ""
    if upvalue_captures:
        upval_parts = ", ".join(f"{name} ({typ})" for name, typ in upvalue_captures)
        upval_comment = f"{inner_prefix}-- upvalues: {upval_parts}\n"

    body_str = format_body(closure.body, indent + 1)
    prefix = INDENT * indent

    if not body_str and not upval_comment:
        return f"function({params_str}){line_annotation}{name_annotation}\n{prefix}end"

    body_content = upval_comment + (body_str if body_str else "")
    # If body_content ends with newline from upval_comment (when no body_str), strip trailing newline
    if body_content.endswith("\n") and not body_str:
        body_content = body_content.rstrip("\n")

    return f"function({params_str}){line_annotation}{name_annotation}\n{body_content}\n{prefix}end"
