from dataclasses import dataclass
from .lib import Expression


@dataclass
class UnaryOp(Expression):
    """A unary operation: op operand

    Supported ops: -, not, #
    """
    op: str = ""
    operand: Expression = None
