"""Type system utilities for the AST.

Provides basic type inference hints that can be attached to AST nodes
to assist in decompilation. Luau has an optional type system, and the
bytecode may carry type annotations that we can reconstruct.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class LuaType:
    """Base class for Lua type representations."""
    pass


@dataclass
class NilType(LuaType):
    """The nil type."""
    def __str__(self):
        return "nil"


@dataclass
class BooleanType(LuaType):
    """The boolean type."""
    def __str__(self):
        return "boolean"


@dataclass
class NumberType(LuaType):
    """The number type."""
    def __str__(self):
        return "number"


@dataclass
class StringType(LuaType):
    """The string type."""
    def __str__(self):
        return "string"


@dataclass
class TableType(LuaType):
    """A table type with optional key and value types."""
    key_type: Optional[LuaType] = None
    value_type: Optional[LuaType] = None

    def __str__(self):
        if self.key_type and self.value_type:
            return f"{{{self.key_type}: {self.value_type}}}"
        return "table"


@dataclass
class FunctionType(LuaType):
    """A function type with parameter and return types."""
    param_types: List[LuaType] = field(default_factory=list)
    return_types: List[LuaType] = field(default_factory=list)
    is_vararg: bool = False

    def __str__(self):
        params = ", ".join(str(t) for t in self.param_types)
        if self.is_vararg:
            params += (", " if params else "") + "..."
        returns = ", ".join(str(t) for t in self.return_types)
        return f"({params}) -> ({returns})"


@dataclass
class AnyType(LuaType):
    """The 'any' type - used when type is unknown."""
    def __str__(self):
        return "any"


@dataclass
class UnionType(LuaType):
    """A union of multiple types."""
    types: List[LuaType] = field(default_factory=list)

    def __str__(self):
        return " | ".join(str(t) for t in self.types)


def infer_type(node) -> Optional[LuaType]:
    """Attempt to infer the type of an AST expression node.

    Returns None if the type cannot be determined.
    """
    from .literal import NumberLiteral, StringLiteral, BoolLiteral, NilLiteral

    if isinstance(node, NumberLiteral):
        return NumberType()
    elif isinstance(node, StringLiteral):
        return StringType()
    elif isinstance(node, BoolLiteral):
        return BooleanType()
    elif isinstance(node, NilLiteral):
        return NilType()

    return None
