from dataclasses import dataclass
from .lib import Statement


@dataclass
class CloseUpvalues(Statement):
    """Close upvalues at a given register.

    This is an internal bytecode operation that typically doesn't
    appear in the final decompiled output.
    """
    reg: int = 0
