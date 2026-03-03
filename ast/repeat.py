from dataclasses import dataclass
from .lib import Expression, Statement, Body


@dataclass
class RepeatUntil(Statement):
    """A repeat-until loop: repeat ... until condition"""
    condition: Expression = None
    body: Body = None

    def __post_init__(self):
        if self.body is None:
            self.body = Body()
