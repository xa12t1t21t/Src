from dataclasses import dataclass, field
from typing import List, Optional
from .lib import Expression


@dataclass
class TableField:
    """A single field in a table constructor.

    If key is None, this is an array-part entry (positional).
    If key is a StringLiteral with a valid identifier, formats as: key = value
    Otherwise formats as: [key] = value
    """
    key: Optional[Expression] = None
    value: Expression = None

    def __post_init__(self):
        if self.value is None:
            from .literal import NilLiteral
            self.value = NilLiteral()


@dataclass
class TableConstructor(Expression):
    """A table constructor expression: {field1, field2, ...}"""
    fields: List[TableField] = field(default_factory=list)
