from dataclasses import dataclass
from .lib import Expression


@dataclass
class IndexExpression(Expression):
    """An index expression: table[key]"""
    table: Expression = None
    key: Expression = None


@dataclass
class DotExpression(Expression):
    """A dot-access expression: table.field_name"""
    table: Expression = None
    field_name: str = ""
