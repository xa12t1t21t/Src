from dataclasses import dataclass
from .lib import Expression


@dataclass
class Local:
    """Represents a local variable declaration."""
    name: str = ""
    reg: int = -1


@dataclass
class LocalRef(Expression):
    """A reference to a local variable."""
    local: Local = None

    def __post_init__(self):
        if self.local is None:
            self.local = Local()
