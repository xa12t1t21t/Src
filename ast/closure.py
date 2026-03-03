from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from .lib import Expression, Body
from .local import Local


@dataclass
class Closure(Expression):
    """A function/closure expression: function(params) ... end"""
    params: List[Local] = field(default_factory=list)
    is_vararg: bool = False
    body: Body = None
    debug_name: Optional[str] = None
    line_defined: Optional[int] = None
    upvalue_captures: List[Tuple[str, str]] = field(default_factory=list)

    def __post_init__(self):
        if self.body is None:
            self.body = Body()
