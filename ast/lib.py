from dataclasses import dataclass, field
from typing import List, Optional


class ASTNode:
    """Base class for all AST nodes."""
    pass


class Expression(ASTNode):
    """Base class for all expression nodes."""
    pass


class Statement(ASTNode):
    """Base class for all statement nodes."""
    pass


@dataclass
class Body:
    """Represents a block of statements (function body, loop body, etc.)."""
    statements: List[Statement] = field(default_factory=list)

    def __str__(self):
        from .formatter import format_body
        return format_body(self)
