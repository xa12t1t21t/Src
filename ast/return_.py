from dataclasses import dataclass, field
from typing import List
from .lib import Expression, Statement


@dataclass
class Return(Statement):
    """A return statement: return expr1, expr2, ..."""
    values: List[Expression] = field(default_factory=list)
