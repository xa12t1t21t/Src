from dataclasses import dataclass
from .lib import Expression


@dataclass
class BinaryOp(Expression):
    """A binary operation: left op right

    Supported ops: +, -, *, /, //, %, ^, ..,
                   ==, ~=, <, <=, >, >=,
                   and, or
    """
    op: str = ""
    left: Expression = None
    right: Expression = None
