"""Luau bytecode lifter - transforms deserialized bytecode into AST nodes.

This package implements the "lifting" phase of the Luau decompiler, which
takes the raw deserialized bytecode instructions and produces a high-level
AST representation.
"""

from .lifter import Lifter
from .main import decompile, decompile_chunk, lift_chunk
from .op_code import LuauOpcode
from .instruction import get_jump_target, is_jump, is_for_prep, is_for_loop
from .lib import resolve_string, resolve_constant_string, resolve_import_name

__all__ = [
    "Lifter",
    "decompile",
    "decompile_chunk",
    "lift_chunk",
    "LuauOpcode",
    "get_jump_target",
    "is_jump",
    "is_for_prep",
    "is_for_loop",
    "resolve_string",
    "resolve_constant_string",
    "resolve_import_name",
]
