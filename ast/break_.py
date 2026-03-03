from dataclasses import dataclass
from .lib import Statement


@dataclass
class Break(Statement):
    """A break statement."""
    pass
