from .reader import BytecodeReader
from .types import Chunk, Proto, Constant, ConstantType, Instruction, LocalVar
from .opcodes import LuauOpcode, HAS_AUX


def deserialize(bytecode: bytes, encode_key: int = 1) -> Chunk:
    reader = BytecodeReader(bytecode)
    chunk = Chunk()

    # Version byte
    chunk.version = reader.read_byte()
    if chunk.version == 0:
        # Error: rest of the data is an error message
        error_msg = reader.read_bytes(reader.remaining()).decode("utf-8", errors="replace")
        raise ValueError(f"Bytecode error: {error_msg}")

    # Types version (version >= 4)
    if chunk.version >= 4:
        chunk.types_version = reader.read_byte()

    # String table
    string_count = reader.read_varint()
    for _ in range(string_count):
        length = reader.read_varint()
        s = reader.read_string(length)
        chunk.string_table.append(s)

    # Userdata type remapping (version >= 5)
    if chunk.version >= 5:
        userdata_type_count = reader.read_varint()
        for _ in range(userdata_type_count):
            _type_idx = reader.read_varint()
            _name_idx = reader.read_varint()

    # Proto table
    proto_count = reader.read_varint()
    for _ in range(proto_count):
        proto = _read_proto(reader, chunk.version, chunk.types_version, encode_key, chunk.string_table)
        chunk.protos.append(proto)

    # Main proto index
    chunk.main_proto = reader.read_varint()

    return chunk


def _read_proto(reader: BytecodeReader, version: int, types_version: int, encode_key: int, string_table: list) -> Proto:
    proto = Proto()

    proto.max_stack_size = reader.read_byte()
    proto.num_params = reader.read_byte()
    proto.num_upvalues = reader.read_byte()
    proto.is_vararg = bool(reader.read_byte())

    # Flags (version >= 6)
    if version >= 6:
        proto.flags = reader.read_byte()

    # Type info (types_version >= 1)
    if types_version >= 1:
        type_info_size = reader.read_varint()
        if type_info_size > 0:
            proto.type_info = reader.read_bytes(type_info_size)

    # Instructions
    size_code = reader.read_varint()
    raw_instructions = []
    for _ in range(size_code):
        raw_instructions.append(reader.read_uint32())

    # Decode instructions and attach AUX words
    pc = 0
    while pc < len(raw_instructions):
        raw = raw_instructions[pc]
        insn = Instruction.decode(raw, encode_key)
        insn.pc = pc

        # Check if this opcode has an AUX word
        try:
            op = LuauOpcode(insn.opcode)
            if op in HAS_AUX and pc + 1 < len(raw_instructions):
                insn.aux = raw_instructions[pc + 1]
                proto.instructions.append(insn)
                pc += 2
                continue
        except ValueError:
            pass  # Unknown opcode, no AUX

        proto.instructions.append(insn)
        pc += 1

    # Constants
    size_k = reader.read_varint()
    for _ in range(size_k):
        const = _read_constant(reader)
        proto.constants.append(const)

    # Child proto indices
    size_p = reader.read_varint()
    for _ in range(size_p):
        proto.child_protos.append(reader.read_varint())

    # Line defined (version >= 6)
    if version >= 6:
        proto.line_defined = reader.read_varint()

    # Debug name
    proto.debug_name_idx = reader.read_varint()

    # Line info
    has_line_info = reader.read_byte()
    if has_line_info:
        proto.line_gap_log2 = reader.read_byte()
        line_gap = 1 << proto.line_gap_log2

        # Per-instruction line offsets (one byte per instruction in sizecode)
        for _ in range(size_code):
            proto.line_info.append(reader.read_byte())

        # Absolute line info entries
        intervals = ((size_code - 1) >> proto.line_gap_log2) + 1
        last_offset = 0
        for _ in range(intervals):
            last_offset += reader.read_int32()
            proto.abs_line_info.append(last_offset)



    # Debug info
    has_debug_info = reader.read_byte()
    if has_debug_info:
        # Local variables
        local_count = reader.read_varint()
        for _ in range(local_count):
            name_idx = reader.read_varint()
            start_pc = reader.read_varint()
            end_pc = reader.read_varint()
            reg = reader.read_byte()
            # Resolve name from string table (1-based index)
            if 1 <= name_idx <= len(string_table):
                resolved_name = string_table[name_idx - 1]
            else:
                resolved_name = None
            proto.local_vars.append(LocalVar(
                name=resolved_name,
                start_pc=start_pc,
                end_pc=end_pc,
                reg=reg,
            ))

        # Upvalue names
        upvalue_count = reader.read_varint()
        for _ in range(upvalue_count):
            name_idx = reader.read_varint()
            if 1 <= name_idx <= len(string_table):
                proto.upvalue_names.append(string_table[name_idx - 1])
            else:
                proto.upvalue_names.append(f"upval_{name_idx}")

    return proto



def _read_constant(reader: BytecodeReader) -> Constant:
    const_type = reader.read_byte()

    if const_type == ConstantType.NIL:
        return Constant(type=ConstantType.NIL)

    elif const_type == ConstantType.BOOLEAN:
        val = reader.read_byte()
        return Constant(type=ConstantType.BOOLEAN, value_bool=bool(val))

    elif const_type == ConstantType.NUMBER:
        val = reader.read_float64()
        return Constant(type=ConstantType.NUMBER, value_number=val)

    elif const_type == ConstantType.STRING:
        idx = reader.read_varint()
        return Constant(type=ConstantType.STRING, value_string_idx=idx)

    elif const_type == ConstantType.IMPORT:
        iid = reader.read_uint32()
        return Constant(type=ConstantType.IMPORT, value_import=iid)

    elif const_type == ConstantType.TABLE:
        count = reader.read_varint()
        keys = []
        for _ in range(count):
            keys.append(reader.read_varint())
        return Constant(type=ConstantType.TABLE, value_table=keys)

    elif const_type == ConstantType.CLOSURE:
        fid = reader.read_varint()
        return Constant(type=ConstantType.CLOSURE, value_closure=fid)

    elif const_type == ConstantType.VECTOR:
        x = reader.read_float32()
        y = reader.read_float32()
        z = reader.read_float32()
        w = reader.read_float32()
        return Constant(type=ConstantType.VECTOR, value_vector=(x, y, z, w))

    else:
        raise ValueError(f"Unknown constant type {const_type} at reader position {reader.pos}")
