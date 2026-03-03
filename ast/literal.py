from dataclasses import dataclass
from .lib import Expression


@dataclass
class NumberLiteral(Expression):
    """A numeric literal value."""
    value: float = 0.0


@dataclass
class StringLiteral(Expression):
    """A string literal value."""
    value: str = ""


@dataclass
class BoolLiteral(Expression):
    """A boolean literal value (true/false)."""
    value: bool = False


@dataclass
class NilLiteral(Expression):
    """The nil literal."""
    pass
