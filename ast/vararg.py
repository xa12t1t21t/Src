from dataclasses import dataclass
from .lib import Expression


@dataclass
class VarargExpression(Expression):
    """The vararg expression: ..."""
    pass
