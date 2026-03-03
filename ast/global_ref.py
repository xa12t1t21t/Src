from dataclasses import dataclass
from .lib import Expression


@dataclass
class GlobalRef(Expression):
    """A reference to a global variable."""
    name: str = ""
