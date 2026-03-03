"""Entry point for the Luau bytecode decompiler.

Provides the top-level decompile() function that takes raw bytecode bytes
and returns formatted Lua source code.
"""

from deserializer import deserialize
from deserializer.types import Chunk

from ast.src.lib import Body

from .lifter import Lifter
from ast.src.name_locals import name_locals


def decompile(bytecode: bytes, encode_key: int = 203) -> str:
    """Decompile Luau bytecode into Lua source code.

    This is the main entry point for decompilation. It:
    1. Deserializes the raw bytecode into a Chunk
    2. Lifts the bytecode instructions into an AST
    3. Formats the AST back into Lua source code

    Args:
        bytecode: Raw Luau bytecode bytes.
        encode_key: The opcode encoding key used in the bytecode.
            Defaults to 203 (common Luau encoding key).

    Returns:
        A string containing the decompiled Lua source code.
    """
    chunk = deserialize(bytecode, encode_key)
    lifter = Lifter(chunk)
    body = lifter.lift()
    name_locals(body)
    return str(body)


def decompile_chunk(chunk: Chunk) -> str:
    """Decompile a pre-deserialized Chunk into Lua source code.

    Use this when you already have a deserialized Chunk object
    (e.g. for testing or when using a custom deserialization pipeline).

    Args:
        chunk: A deserialized Luau bytecode Chunk.

    Returns:
        A string containing the decompiled Lua source code.
    """
    lifter = Lifter(chunk)
    body = lifter.lift()
    name_locals(body)
    return str(body)


def lift_chunk(chunk: Chunk) -> Body:
    """Lift a pre-deserialized Chunk into an AST Body.

    Returns the raw AST without formatting, which is useful for
    further analysis or transformation passes.

    Args:
        chunk: A deserialized Luau bytecode Chunk.

    Returns:
        A Body AST node containing the lifted statements.
    """
    lifter = Lifter(chunk)
    body = lifter.lift()
    name_locals(body)
    return body
