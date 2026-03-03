from dataclasses import dataclass, field
from typing import List
from .lib import Expression, Statement


@dataclass
class Assignment(Statement):
    """An assignment statement: targets = values"""
    targets: List[Expression] = field(default_factory=list)
    values: List[Expression] = field(default_factory=list)
