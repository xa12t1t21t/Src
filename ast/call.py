from dataclasses import dataclass, field
from typing import List
from .lib import Expression, Statement


@dataclass
class FunctionCall(Expression):
    """A function call expression: func(args)"""
    func: Expression = None
    args: List[Expression] = field(default_factory=list)


@dataclass
class MethodCall(Expression):
    """A method call expression: object:method(args)"""
    object: Expression = None
    method: str = ""
    args: List[Expression] = field(default_factory=list)


@dataclass
class FunctionCallStatement(Statement):
    """Wraps a FunctionCall or MethodCall as a statement."""
    call: Expression = None
