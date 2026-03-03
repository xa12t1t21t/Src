"""Assigns human-readable names to Local objects based on usage context.

This pass walks the AST and assigns names to Local objects that don't
already have meaningful names (e.g., those generated from register numbers).
"""

from typing import Optional
from .lib import Body, Statement
from .local import Local, LocalRef
from .local_declarations import LocalDeclaration
from .for_ import GenericFor, NumericFor
from .closure import Closure
from .call import FunctionCall, MethodCall, FunctionCallStatement
from .global_ref import GlobalRef
from .name_gen import NameGenerator
from .traverse import walk_statements, walk_expressions
from .index import DotExpression
from .literal import StringLiteral


def _infer_name_from_context(local: Local, stmt: Statement) -> Optional[str]:
    """Try to infer a meaningful name from how the local is used.

    For example, if a local is assigned from a call to `pairs()`,
    we might name the loop variables k, v.
    """
    # Could be extended with more heuristics
    return None


def _needs_naming(local: Local) -> bool:
    """Check if a local needs a new name assigned."""
    if not local.name:
        return True
    # Names like "" or names that are just register references
    if local.name.startswith("reg_") or local.name.startswith("R"):
        return True
    return False


def _is_upval_placeholder(name: str) -> bool:
    """Return True if the name is a decompiler-generated upvalue placeholder like upval_0."""
    if not name.startswith("upval_"):
        return False
    return name[6:].isdigit()


def _rename_upvalue_globals(body: Body, generator: NameGenerator):
    """Rename upvalue placeholder GlobalRef nodes (upval_N) to readable short names.

    The lifter emits GlobalRef("upval_0"), GlobalRef("upval_1"), etc. for upvalues
    whose names were stripped from the bytecode debug info. This pass assigns them
    the same short-name scheme (v1, v2, ...) used for regular locals.

    A global mapping is used so that every occurrence of the same upvalue placeholder
    name consistently gets the same new name throughout the entire body (including
    nested closure bodies), since GlobalRef nodes are treated as global-scoped.
    """
    upval_map: dict = {}

    # First pass: collect all unique upval_N names and assign new names
    for expr in walk_expressions(body):
        if isinstance(expr, GlobalRef) and _is_upval_placeholder(expr.name):
            if expr.name not in upval_map:
                upval_map[expr.name] = generator.next_var()

    # Second pass: apply the renames in-place
    for expr in walk_expressions(body):
        if isinstance(expr, GlobalRef) and expr.name in upval_map:
            expr.name = upval_map[expr.name]

    # Third pass: update upvalue_captures on Closure nodes so the comment matches
    if upval_map:
        for expr in walk_expressions(body):
            if isinstance(expr, Closure) and expr.upvalue_captures:
                expr.upvalue_captures = [
                    (upval_map.get(name, name), typ)
                    for name, typ in expr.upvalue_captures
                ]


# Methods that take a string name argument and whose result should be l_-named
_NAMED_METHODS = frozenset({
    "FindFirstChild", "WaitForChild", "FindFirstChildOfClass",
    "FindFirstChildWhichIsA", "FindFirstAncestorWhichIsA",
    "FindFirstAncestorOfClass", "GetService",
})


def _get_l_prefix(value) -> Optional[str]:
    """Extract a base name for l_ prefix naming from an expression value.

    Returns the base name (without l_ prefix and without _N suffix) or None.
    Applies to: GetService, FindFirstChild/WaitForChild family, Instance.new, DotExpression.
    """
    # game:GetService("X") or FindFirstChild("X"), WaitForChild("X"), etc.
    if isinstance(value, MethodCall):
        if value.method in _NAMED_METHODS and len(value.args) == 1:
            arg = value.args[0]
            if isinstance(arg, StringLiteral):
                return arg.value

    # Instance.new("ClassName") → l_ClassName_0
    # Detected as FunctionCall where func is DotExpression(GlobalRef("Instance"), "new")
    if isinstance(value, FunctionCall):
        func = value.func
        if (isinstance(func, DotExpression) and func.field_name == "new"
                and isinstance(func.table, GlobalRef) and func.table.name == "Instance"
                and len(value.args) >= 1 and isinstance(value.args[0], StringLiteral)):
            return value.args[0].value

    # someVar.PropertyName → l_PropertyName_0 (any dot access)
    if isinstance(value, DotExpression):
        return value.field_name

    return None


def _assign_semantic_names(body: Body, generator: NameGenerator, prefix_counts: dict):
    """Assign l_X_N names to locals based on their value expressions.

    Walks LocalDeclaration statements and assigns l_ prefixed names to locals
    whose values match known patterns (GetService, common properties).

    Args:
        body: The AST body to process.
        generator: Name generator to reserve names.
        prefix_counts: Shared dict tracking count per l_ prefix across all scopes.
    """
    for stmt in body.statements:
        if isinstance(stmt, LocalDeclaration):
            for i, local in enumerate(stmt.locals):
                # Skip if already has a semantic l_ name
                if local.name and local.name.startswith('l_'):
                    continue
                value = stmt.values[i] if i < len(stmt.values) else None
                if value is None:
                    continue
                base = _get_l_prefix(value)
                if base is None:
                    continue
                # Allocate l_Base_N
                prefix_key = f"l_{base}"
                count = prefix_counts.get(prefix_key, 0)
                prefix_counts[prefix_key] = count + 1
                name = f"{prefix_key}_{count}"
                local.name = name
                generator.reserve(name)

        # Recurse into nested bodies
        if isinstance(stmt, (GenericFor, NumericFor)):
            _assign_semantic_names(stmt.body, generator, prefix_counts)
        elif hasattr(stmt, 'body') and isinstance(getattr(stmt, 'body', None), Body):
            _assign_semantic_names(getattr(stmt, 'body'), generator, prefix_counts)
        if hasattr(stmt, 'then_body') and isinstance(getattr(stmt, 'then_body', None), Body):
            _assign_semantic_names(stmt.then_body, generator, prefix_counts)
        if hasattr(stmt, 'else_body') and getattr(stmt, 'else_body', None) is not None:
            _assign_semantic_names(stmt.else_body, generator, prefix_counts)
        if hasattr(stmt, 'elseif_clauses'):
            for _, elseif_body in getattr(stmt, 'elseif_clauses', []):
                _assign_semantic_names(elseif_body, generator, prefix_counts)

    # Recurse into closures in expressions
    for expr in walk_expressions(body):
        if isinstance(expr, Closure):
            _assign_semantic_names(expr.body, generator, prefix_counts)


def name_locals(body: Body, generator: Optional[NameGenerator] = None):
    """Assign names to all unnamed Local objects in the body.

    Walks the AST and assigns names based on context:
    - Numeric for loop variables get 'i', 'j', etc.
    - Generic for loop variables get 'k', 'v' or similar
    - Function parameters get 'a', 'b', 'c', etc.
    - Other locals get 'v1', 'v2', etc.

    Args:
        body: The AST body to process.
        generator: Optional NameGenerator. If None, a new one is created.
    """
    if generator is None:
        generator = NameGenerator()

    # First pass: collect all locals that already have good names
    # and reserve them so we don't generate duplicates
    _reserve_existing_names(body, generator)

    # Semantic pass: assign l_ prefixed names for known patterns
    _assign_semantic_names(body, generator, {})

    # Second pass: assign names to unnamed locals
    _assign_names(body, generator)

    _rename_upvalue_globals(body, generator)


def _reserve_existing_names(body: Body, generator: NameGenerator):
    """Reserve all existing meaningful local names."""
    for stmt in walk_statements(body):
        if isinstance(stmt, LocalDeclaration):
            for local in stmt.locals:
                if local.name and not _needs_naming(local):
                    generator.reserve(local.name)
        elif isinstance(stmt, GenericFor):
            for local in stmt.vars:
                if local.name and not _needs_naming(local):
                    generator.reserve(local.name)
            _reserve_existing_names(stmt.body, generator)
        elif isinstance(stmt, NumericFor):
            if stmt.var.name and not _needs_naming(stmt.var):
                generator.reserve(stmt.var.name)
            _reserve_existing_names(stmt.body, generator)

    # Also walk expressions for closures
    for expr in walk_expressions(body):
        if isinstance(expr, Closure):
            for param in expr.params:
                if param.name and not _needs_naming(param):
                    generator.reserve(param.name)
            _reserve_existing_names(expr.body, generator)


def _assign_names(body: Body, generator: NameGenerator):
    """Assign names to all unnamed locals in the body."""
    for stmt in body.statements:
        if isinstance(stmt, LocalDeclaration):
            for local in stmt.locals:
                if _needs_naming(local):
                    local.name = generator.next_var()

        elif isinstance(stmt, GenericFor):
            for local in stmt.vars:
                if _needs_naming(local):
                    names = generator.for_loop_vars(len(stmt.vars))
                    # Only assign to the ones that need naming
                    for i, var in enumerate(stmt.vars):
                        if _needs_naming(var) and i < len(names):
                            var.name = names[i]
                    break  # We named them all in one go
            _assign_names(stmt.body, generator)

        elif isinstance(stmt, NumericFor):
            if _needs_naming(stmt.var):
                stmt.var.name = generator.numeric_for_var()
            _assign_names(stmt.body, generator)

        # Recurse into sub-bodies
        elif hasattr(stmt, 'body') and isinstance(getattr(stmt, 'body'), Body):
            _assign_names(getattr(stmt, 'body'), generator)
        if hasattr(stmt, 'then_body') and isinstance(getattr(stmt, 'then_body'), Body):
            _assign_names(stmt.then_body, generator)
        if hasattr(stmt, 'else_body') and getattr(stmt, 'else_body') is not None:
            _assign_names(stmt.else_body, generator)
        if hasattr(stmt, 'elseif_clauses'):
            for _, elseif_body in getattr(stmt, 'elseif_clauses', []):
                _assign_names(elseif_body, generator)

    # Walk expressions for closures
    for expr in walk_expressions(body):
        if isinstance(expr, Closure):
            for i, param in enumerate(expr.params):
                if _needs_naming(param):
                    param.name = generator.func_param(i)
            _assign_names(expr.body, generator)
