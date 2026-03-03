from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from .lib import Expression, Statement, Body


@dataclass
class IfStatement(Statement):
    """An if/elseif/else statement.

    elseif_clauses is a list of (condition, body) tuples.
    """
    condition: Expression = None
    then_body: Body = None
    elseif_clauses: List[Tuple[Expression, Body]] = field(default_factory=list)
    else_body: Optional[Body] = None

    def __post_init__(self):
        if self.then_body is None:
            self.then_body = Body()
