from dataclasses import dataclass
from .lib import Statement


@dataclass
class Goto(Statement):
    """A goto statement: goto label"""
    label: str = ""


@dataclass
class Label(Statement):
    """A label statement: ::name::"""
    name: str = ""
