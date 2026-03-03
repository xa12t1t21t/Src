from dataclasses import dataclass
from .lib import Expression, Statement, Body


@dataclass
class WhileLoop(Statement):
    """A while loop: while condition do ... end"""
    condition: Expression = None
    body: Body = None

    def __post_init__(self):
        if self.body is None:
            self.body = Body()
