import importlib
import os
import sys
from deserializer import deserialize, opcode_name, ConstantType, LuauOpcode


def get_line_number(proto, pc):
    """Get the source line number for a given PC using line info.

    line_info entries are signed int8 deltas. The line for a given PC is
    computed as: abs_line_info[interval] + sum of signed deltas from
    the interval start through pc (inclusive).
    """
    if not proto.abs_line_info or not proto.line_info:
        return None
    if pc >= len(proto.line_info):
        return None

    gap = 1 << proto.line_gap_log2
    interval = pc >> proto.line_gap_log2
    if interval >= len(proto.abs_line_info):
        return None

    base = proto.abs_line_info[interval]
    start = interval * gap
    offset = 0
    for j in range(start, pc + 1):
        if j < len(proto.line_info):
            delta = proto.line_info[j]
            if delta > 127:
                delta -= 256  # treat as signed int8
            offset += delta
    return base + offset


def resolve_string(chunk, idx):
    """Resolve a 1-based string table index to a string."""
    if idx == 0:
        return "<none>"
    if 1 <= idx <= len(chunk.string_table):
        return chunk.string_table[idx - 1]
    return f"<invalid_string_{idx}>"


def decode_import(iid):
    """Decode an import id into its chain of constant table indices."""
    count = (iid >> 30) & 0x3
    ids = []
    if count >= 1:
        ids.append((iid >> 20) & 0x3FF)
    if count >= 2:
        ids.append((iid >> 10) & 0x3FF)
    if count >= 3:
        ids.append(iid & 0x3FF)
    return ids


def resolve_import_name(chunk, proto, iid):
    """Resolve an import id to a human-readable dotted name."""
    const_indices = decode_import(iid)
    parts = []
    for ci in const_indices:
        if ci < len(proto.constants):
            k = proto.constants[ci]
            if k.type == ConstantType.STRING:
                parts.append(resolve_string(chunk, k.value_string_idx))
            else:
                parts.append(f"K{ci}")
        else:
            parts.append(f"K{ci}?")
    return ".".join(parts) if parts else "<unknown_import>"


def format_constant(chunk, proto, k, idx):
    """Format a constant for display."""
    if k.type == ConstantType.NIL:
        return "nil"
    elif k.type == ConstantType.BOOLEAN:
        return str(k.value_bool).lower()
    elif k.type == ConstantType.NUMBER:
        if k.value_number == int(k.value_number):
            return str(int(k.value_number))
        return str(k.value_number)
    elif k.type == ConstantType.STRING:
        return f'"{resolve_string(chunk, k.value_string_idx)}"'
    elif k.type == ConstantType.IMPORT:
        return f"import({resolve_import_name(chunk, proto, k.value_import)})"
    elif k.type == ConstantType.TABLE:
        keys = []
        for ki in k.value_table:
            if ki < len(proto.constants):
                keys.append(format_constant(chunk, proto, proto.constants[ki], ki))
            else:
                keys.append(f"K{ki}?")
        return f"table_template{{{', '.join(keys)}}}"
    elif k.type == ConstantType.CLOSURE:
        return f"closure(proto_{k.value_closure})"
    elif k.type == ConstantType.VECTOR:
        return f"vector({k.value_vector})"
    return f"<unknown>"


def format_instruction(chunk, proto, insn):
    """Format an instruction for display."""
    op = insn.opcode
    name = opcode_name(op)
    parts = [f"[{insn.pc:3d}] {name:<20s}"]

    try:
        luau_op = LuauOpcode(op)
    except ValueError:
        parts.append(f"A={insn.a} B={insn.b} C={insn.c}")
        return " ".join(parts)

    # Format based on opcode
    if luau_op == LuauOpcode.PREPVARARGS:
        parts.append(f"A={insn.a}")
    elif luau_op == LuauOpcode.LOADN:
        parts.append(f"R{insn.a} = {insn.d}")
    elif luau_op == LuauOpcode.LOADK:
        val = format_constant(chunk, proto, proto.constants[insn.d], insn.d) if insn.d < len(proto.constants) else f"K{insn.d}"
        parts.append(f"R{insn.a} = {val}")
    elif luau_op == LuauOpcode.LOADNIL:
        parts.append(f"R{insn.a} = nil")
    elif luau_op == LuauOpcode.LOADB:
        parts.append(f"R{insn.a} = {bool(insn.b)}")
        if insn.c:
            parts.append(f"(skip {insn.c})")
    elif luau_op == LuauOpcode.MOVE:
        parts.append(f"R{insn.a} = R{insn.b}")
    elif luau_op == LuauOpcode.GETGLOBAL:
        aux_str = resolve_string(chunk, insn.aux) if insn.aux is not None else "?"
        parts.append(f"R{insn.a} = _G['{aux_str}']")
    elif luau_op == LuauOpcode.SETGLOBAL:
        aux_str = resolve_string(chunk, insn.aux) if insn.aux is not None else "?"
        parts.append(f"_G['{aux_str}'] = R{insn.a}")
    elif luau_op == LuauOpcode.GETUPVAL:
        parts.append(f"R{insn.a} = upvalue[{insn.b}]")
    elif luau_op == LuauOpcode.SETUPVAL:
        parts.append(f"upvalue[{insn.b}] = R{insn.a}")
    elif luau_op == LuauOpcode.GETIMPORT:
        if insn.aux is not None:
            import_name = resolve_import_name(chunk, proto, insn.aux)
            parts.append(f"R{insn.a} = {import_name}")
        else:
            parts.append(f"R{insn.a} = import(K{insn.d})")
    elif luau_op == LuauOpcode.GETTABLE:
        parts.append(f"R{insn.a} = R{insn.b}[R{insn.c}]")
    elif luau_op == LuauOpcode.SETTABLE:
        parts.append(f"R{insn.b}[R{insn.c}] = R{insn.a}")
    elif luau_op == LuauOpcode.GETTABLEKS:
        if insn.aux is not None and insn.aux < len(proto.constants):
            key = format_constant(chunk, proto, proto.constants[insn.aux], insn.aux)
            parts.append(f"R{insn.a} = R{insn.b}[{key}]")
        else:
            parts.append(f"R{insn.a} = R{insn.b}[K_AUX]")
    elif luau_op == LuauOpcode.SETTABLEKS:
        if insn.aux is not None and insn.aux < len(proto.constants):
            key = format_constant(chunk, proto, proto.constants[insn.aux], insn.aux)
            parts.append(f"R{insn.b}[{key}] = R{insn.a}")
        else:
            parts.append(f"R{insn.b}[K_AUX] = R{insn.a}")
    elif luau_op == LuauOpcode.GETTABLEN:
        parts.append(f"R{insn.a} = R{insn.b}[{insn.c + 1}]")
    elif luau_op == LuauOpcode.SETTABLEN:
        parts.append(f"R{insn.b}[{insn.c + 1}] = R{insn.a}")
    elif luau_op == LuauOpcode.DUPTABLE:
        if insn.d < len(proto.constants):
            val = format_constant(chunk, proto, proto.constants[insn.d], insn.d)
            parts.append(f"R{insn.a} = {val}")
        else:
            parts.append(f"R{insn.a} = duptable(K{insn.d})")
    elif luau_op == LuauOpcode.NEWTABLE:
        aux = insn.aux if insn.aux is not None else 0
        parts.append(f"R{insn.a} = {{}} (size={insn.b}, array={aux})")
    elif luau_op == LuauOpcode.NEWCLOSURE:
        parts.append(f"R{insn.a} = closure(proto_{insn.d})")
    elif luau_op == LuauOpcode.DUPCLOSURE:
        if insn.d < len(proto.constants):
            parts.append(f"R{insn.a} = dupclosure(K{insn.d})")
        else:
            parts.append(f"R{insn.a} = dupclosure(K{insn.d})")
    elif luau_op == LuauOpcode.NAMECALL:
        if insn.aux is not None and insn.aux < len(proto.constants):
            key = format_constant(chunk, proto, proto.constants[insn.aux], insn.aux)
            parts.append(f"R{insn.a} = R{insn.b}:{key}")
        else:
            parts.append(f"R{insn.a} = R{insn.b}:method")
    elif luau_op == LuauOpcode.CALL:
        nargs = insn.b - 1 if insn.b > 0 else "vararg"
        nresults = insn.c - 1 if insn.c > 0 else "vararg"
        parts.append(f"R{insn.a}({nargs} args, {nresults} results)")
    elif luau_op == LuauOpcode.RETURN:
        nresults = insn.b - 1 if insn.b > 0 else "vararg"
        parts.append(f"R{insn.a}.. ({nresults} values)")
    elif luau_op in (LuauOpcode.JUMP, LuauOpcode.JUMPBACK):
        target = insn.pc + insn.d + 1
        parts.append(f"-> [{target}]")
    elif luau_op in (LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT):
        target = insn.pc + insn.d + 1
        parts.append(f"R{insn.a} -> [{target}]")
    elif luau_op in (LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
                     LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT):
        target = insn.pc + insn.d + 1
        aux_reg = insn.aux & 0xFF if insn.aux is not None else "?"
        parts.append(f"R{insn.a}, R{aux_reg} -> [{target}]")
    elif luau_op in (LuauOpcode.ADD, LuauOpcode.SUB, LuauOpcode.MUL, LuauOpcode.DIV,
                     LuauOpcode.MOD, LuauOpcode.POW, LuauOpcode.IDIV):
        ops = {LuauOpcode.ADD: "+", LuauOpcode.SUB: "-", LuauOpcode.MUL: "*",
               LuauOpcode.DIV: "/", LuauOpcode.MOD: "%", LuauOpcode.POW: "^",
               LuauOpcode.IDIV: "//"}
        parts.append(f"R{insn.a} = R{insn.b} {ops[luau_op]} R{insn.c}")
    elif luau_op in (LuauOpcode.ADDK, LuauOpcode.SUBK, LuauOpcode.MULK, LuauOpcode.DIVK,
                     LuauOpcode.MODK, LuauOpcode.POWK, LuauOpcode.IDIVK):
        ops = {LuauOpcode.ADDK: "+", LuauOpcode.SUBK: "-", LuauOpcode.MULK: "*",
               LuauOpcode.DIVK: "/", LuauOpcode.MODK: "%", LuauOpcode.POWK: "^",
               LuauOpcode.IDIVK: "//"}
        kval = format_constant(chunk, proto, proto.constants[insn.c], insn.c) if insn.c < len(proto.constants) else f"K{insn.c}"
        parts.append(f"R{insn.a} = R{insn.b} {ops[luau_op]} {kval}")
    elif luau_op == LuauOpcode.CONCAT:
        parts.append(f"R{insn.a} = R{insn.b} .. ... .. R{insn.c}")
    elif luau_op == LuauOpcode.NOT:
        parts.append(f"R{insn.a} = not R{insn.b}")
    elif luau_op == LuauOpcode.MINUS:
        parts.append(f"R{insn.a} = -R{insn.b}")
    elif luau_op == LuauOpcode.LENGTH:
        parts.append(f"R{insn.a} = #R{insn.b}")
    elif luau_op == LuauOpcode.FORNPREP:
        target = insn.pc + insn.d + 1
        parts.append(f"R{insn.a} prep -> [{target}]")
    elif luau_op == LuauOpcode.FORNLOOP:
        target = insn.pc + insn.d + 1
        parts.append(f"R{insn.a} loop -> [{target}]")
    elif luau_op == LuauOpcode.FORGLOOP:
        target = insn.pc + insn.d + 1
        nresults = insn.aux & 0xFF if insn.aux is not None else "?"
        parts.append(f"R{insn.a} loop ({nresults} vars) -> [{target}]")
    elif luau_op in (LuauOpcode.FORGPREP, LuauOpcode.FORGPREP_NEXT, LuauOpcode.FORGPREP_INEXT):
        target = insn.pc + insn.d + 1
        parts.append(f"R{insn.a} -> [{target}]")
    elif luau_op == LuauOpcode.GETVARARGS:
        n = insn.b - 1 if insn.b > 0 else "all"
        parts.append(f"R{insn.a}.. = ...({n})")
    elif luau_op == LuauOpcode.SETLIST:
        aux = insn.aux if insn.aux is not None else 0
        parts.append(f"R{insn.a}[{aux}..] = R{insn.b}..R{insn.b + insn.c - 1}")
    elif luau_op == LuauOpcode.CLOSEUPVALS:
        parts.append(f"close R{insn.a}+")
    elif luau_op == LuauOpcode.CAPTURE:
        capture_types = {0: "VAL", 1: "REF", 2: "UPVAL"}
        ctype = capture_types.get(insn.a, f"type_{insn.a}")
        parts.append(f"{ctype} R{insn.b}")
    elif luau_op in (LuauOpcode.FASTCALL, LuauOpcode.FASTCALL1, LuauOpcode.FASTCALL2):
        parts.append(f"builtin_{insn.a}()")
    else:
        parts.append(f"A={insn.a} B={insn.b} C={insn.c} D={insn.d}")
        if insn.aux is not None:
            parts.append(f"AUX={insn.aux}")

    return " ".join(parts)


def write_chunk(f, chunk):
    """Write full information about a deserialized chunk to a file object."""
    w = lambda *args, **kwargs: print(*args, **kwargs, file=f)

    w(f"=== Luau Bytecode v{chunk.version} (types v{chunk.types_version}) ===")
    w(f"Main proto: {chunk.main_proto}")
    w()

    # String table
    w(f"--- String Table ({len(chunk.string_table)} strings) ---")
    for i, s in enumerate(chunk.string_table):
        w(f"  [{i}] \"{s}\"")
    w()

    # Protos
    w(f"--- Protos ({len(chunk.protos)} functions) ---")
    for pi, proto in enumerate(chunk.protos):
        is_main = " (MAIN)" if pi == chunk.main_proto else ""
        debug_name = resolve_string(chunk, proto.debug_name_idx) if proto.debug_name_idx else "<anonymous>"
        w(f"\n  Proto {pi}{is_main}: {debug_name}")
        w(f"    maxstack={proto.max_stack_size}, params={proto.num_params}, "
          f"upvalues={proto.num_upvalues}, vararg={proto.is_vararg}, flags={proto.flags}")
        if proto.line_defined:
            w(f"    line_defined={proto.line_defined}")
        if proto.child_protos:
            w(f"    child_protos={proto.child_protos}")

        # Constants
        if proto.constants:
            w(f"\n    Constants ({len(proto.constants)}):")
            for ki, k in enumerate(proto.constants):
                w(f"      K{ki} = {format_constant(chunk, proto, k, ki)}")

        # Instructions
        w(f"\n    Instructions ({len(proto.instructions)}):")
        for insn in proto.instructions:
            line = ""
            if proto.abs_line_info and proto.line_info:
                line_num = get_line_number(proto, insn.pc)
                if line_num is not None:
                    line = f"  ; line {line_num}"
            w(f"      {format_instruction(chunk, proto, insn)}{line}")

        # Local vars
        if proto.local_vars:
            w(f"\n    Local Variables ({len(proto.local_vars)}):")
            for lv in proto.local_vars:
                w(f"      {lv.name} (pc {lv.start_pc}-{lv.end_pc})")

        # Upvalue names
        if proto.upvalue_names:
            w(f"\n    Upvalue Names: {proto.upvalue_names}")


def decompile(bytecode: bytes, encode_key: int) -> str:
    """Decompile bytecode into Lua source code."""
    chunk = deserialize(bytecode, encode_key)
    lifter_mod = importlib.import_module("luau-lifter.src.lifter")
    from ast.src.name_locals import name_locals
    lifter = lifter_mod.Lifter(chunk)
    body = lifter.lift()
    name_locals(body)
    return str(body)


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <bytecode_path> [encode_key]")
        print("Example: python main.py bytecode\\fork_.lua")
        sys.exit(1)

    bytecode_path = sys.argv[1]

    encode_key = 203
    if len(sys.argv) >= 3:
        encode_key = int(sys.argv[2])

    with open(bytecode_path, "rb") as f:
        bytecode = f.read()

    # Build output path: output/<input_filename>
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    input_filename = os.path.basename(bytecode_path)
    output_path = os.path.join(output_dir, input_filename)

    try:
        lua_source = decompile(bytecode, encode_key)

        with open(output_path, "w", encoding="utf-8") as out:
            out.write(lua_source)
            if not lua_source.endswith("\n"):
                out.write("\n")

        print(f"Output written to {output_path}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
