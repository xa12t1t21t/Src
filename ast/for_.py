from dataclasses import dataclass, field
from typing import List, Optional
from .lib import Expression, Statement, Body
from .local import Local


@dataclass
class GenericFor(Statement):
    """A generic for loop: for k, v in iterator do ... end"""
    vars: List[Local] = field(default_factory=list)
    iterators: List[Expression] = field(default_factory=list)
    body: Body = None

    def __post_init__(self):
        if self.body is None:
            self.body = Body()


@dataclass
class NumericFor(Statement):
    """A numeric for loop: for i = start, stop[, step] do ... end"""
    var: Local = None
    start: Expression = None
    stop: Expression = None
    step: Optional[Expression] = None
    body: Body = None

    def __post_init__(self):
        if self.var is None:
            self.var = Local()
        if self.body is None:
            self.body = Body()
