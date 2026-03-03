from dataclasses import dataclass, field
from typing import List
from .lib import Expression, Statement
from .local import Local


@dataclass
class LocalDeclaration(Statement):
    """A local variable declaration: local x, y = expr1, expr2"""
    locals: List[Local] = field(default_factory=list)
    values: List[Expression] = field(default_factory=list)
