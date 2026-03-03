from dataclasses import dataclass
from .lib import Statement


@dataclass
class Continue(Statement):
    """A continue statement (Luau extension)."""
    pass
