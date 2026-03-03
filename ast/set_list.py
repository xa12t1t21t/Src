from dataclasses import dataclass, field
from typing import List
from .lib import Expression, Statement


@dataclass
class SetList(Statement):
    """Set a range of values in a table starting at a given index.

    This corresponds to the SETLIST bytecode instruction and is used
    for initializing array parts of tables.
    """
    table: Expression = None
    start_index: int = 1
    values: List[Expression] = field(default_factory=list)
