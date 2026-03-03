"""Shared utilities for the Luau bytecode lifter.

Provides helper functions for constant resolution, import decoding,
and other common operations needed during bytecode lifting.
"""

from typing import Optional, List
from deserializer.types import Chunk, Proto, Constant, ConstantType


def resolve_string(chunk: Chunk, string_idx: int) -> str:
    """Resolve a 1-based string table index to a string value.

    The Luau bytecode uses 1-based indexing for the string table, where
    index 0 means "no string" / empty.

    Args:
        chunk: The deserialized bytecode chunk containing the string table.
        string_idx: 1-based index into the string table (0 = empty string).

    Returns:
        The resolved string, or empty string if index is 0 or out of range.
    """
    if string_idx == 0:
        return ""
    idx = string_idx - 1
    if 0 <= idx < len(chunk.string_table):
        return chunk.string_table[idx]
    return ""


def resolve_constant_string(chunk: Chunk, proto: Proto, const_idx: int) -> str:
    """Get the string value from a STRING-type constant.

    Looks up the constant at const_idx in the proto's constant pool,
    then resolves its string table reference.

    Args:
        chunk: The deserialized bytecode chunk.
        proto: The proto containing the constant pool.
        const_idx: Index into the proto's constant list.

    Returns:
        The resolved string value.
    """
    k = proto.constants[const_idx]
    if k.type == ConstantType.STRING:
        return resolve_string(chunk, k.value_string_idx)
    return ""


def resolve_import_name(chunk: Chunk, proto: Proto, import_id: int) -> str:
    """Decode an import ID to a dotted name string.

    Luau's GETIMPORT instruction uses an encoded 32-bit import ID that
    packs up to 3 constant indices (each 10 bits) plus a 2-bit count.

    Format:
        bits 30-31: count (1-3 parts)
        bits 20-29: first constant index  (always present if count >= 1)
        bits 10-19: second constant index (present if count >= 2)
        bits  0-9:  third constant index  (present if count >= 3)

    Each constant index references a STRING constant in the proto's constant
    pool, and the parts are joined with dots to form the import name.

    Examples:
        "pairs"       -> count=1, one part
        "math.floor"  -> count=2, two parts joined with "."
        "a.b.c"       -> count=3, three parts joined with "."

    Args:
        chunk: The deserialized bytecode chunk.
        proto: The proto containing the constant pool.
        import_id: The encoded 32-bit import ID (from AUX word).

    Returns:
        The decoded import name as a dotted string.
    """
    count = (import_id >> 30) & 3
    parts = []

    if count >= 1:
        ci = (import_id >> 20) & 0x3FF
        parts.append(resolve_constant_string(chunk, proto, ci))

    if count >= 2:
        ci = (import_id >> 10) & 0x3FF
        parts.append(resolve_constant_string(chunk, proto, ci))

    if count >= 3:
        ci = import_id & 0x3FF
        parts.append(resolve_constant_string(chunk, proto, ci))

    return ".".join(parts)


def constant_to_value(chunk: Chunk, proto: Proto, const_idx: int):
    """Convert a constant to its raw Python value.

    Args:
        chunk: The deserialized bytecode chunk.
        proto: The proto containing the constant pool.
        const_idx: Index into the proto's constant list.

    Returns:
        The Python value (None, bool, float, str, etc.) corresponding to the constant.
    """
    k = proto.constants[const_idx]
    if k.type == ConstantType.NIL:
        return None
    elif k.type == ConstantType.BOOLEAN:
        return k.value_bool
    elif k.type == ConstantType.NUMBER:
        return k.value_number
    elif k.type == ConstantType.STRING:
        return resolve_string(chunk, k.value_string_idx)
    elif k.type == ConstantType.IMPORT:
        return k.value_import
    elif k.type == ConstantType.TABLE:
        return k.value_table
    elif k.type == ConstantType.CLOSURE:
        return k.value_closure
    elif k.type == ConstantType.VECTOR:
        return k.value_vector
    return None
