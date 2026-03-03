"""DOT graph export for CFG visualization.

Generates Graphviz DOT format output that can be rendered with:
    dot -Tpng output.dot -o output.png
"""
from __future__ import annotations

from typing import Optional

from deserializer.opcodes import LuauOpcode, opcode_name


def cfg_to_dot(cfg, show_instructions: bool = True, title: Optional[str] = None) -> str:
    """Convert a FunctionCFG to DOT graph format.

    Args:
        cfg: The FunctionCFG to visualize.
        show_instructions: If True, show instruction mnemonics in block labels.
        title: Optional title for the graph.

    Returns:
        A string in DOT format.
    """
    lines = []
    graph_name = title or f"proto_{cfg.proto_id}"
    lines.append(f'digraph "{graph_name}" {{')
    lines.append('    node [shape=record, fontname="Courier", fontsize=10];')
    lines.append('    edge [fontname="Courier", fontsize=9];')
    lines.append('')

    for block in cfg.blocks:
        label_parts = [f"B{block.id} (pc {block.start_pc}-{block.end_pc})"]

        # Add loop annotations
        annotations = []
        if block.is_loop_header:
            annotations.append("LOOP_HEADER")
        if block.is_loop_latch:
            annotations.append("LOOP_LATCH")
        if block.loop_depth > 0:
            annotations.append(f"depth={block.loop_depth}")
        if annotations:
            label_parts.append(" ".join(annotations))

        # Add phi functions
        for phi in block.phi_functions:
            label_parts.append(str(phi))

        # Add instructions
        if show_instructions and block.instructions:
            for insn in block.instructions:
                mnemonic = opcode_name(insn.opcode)
                detail = _format_instruction_short(insn, mnemonic)
                label_parts.append(detail)

        # Escape special characters for DOT labels
        label = "\\l".join(_escape_dot(p) for p in label_parts) + "\\l"

        # Color loop headers
        style = ""
        if block.is_loop_header:
            style = ', style=filled, fillcolor="#e8f4e8"'
        elif block.is_loop_latch:
            style = ', style=filled, fillcolor="#f4e8e8"'

        if block == cfg.entry_block:
            style += ', penwidth=2'

        lines.append(f'    B{block.id} [label="{{{label}}}"{style}];')

    lines.append('')

    # Add edges
    for block in cfg.blocks:
        for succ in block.successors:
            edge_attrs = []

            # Detect back edges (successor dominates this block)
            if succ.is_loop_header and block.is_loop_latch:
                edge_attrs.append('color=red')
                edge_attrs.append('style=bold')
                edge_attrs.append('label="back"')

            # Label conditional edges
            if len(block.successors) == 2 and block.instructions:
                last = block.instructions[-1]
                try:
                    op = LuauOpcode(last.opcode)
                except ValueError:
                    op = None

                if succ == block.successors[0]:
                    edge_attrs.append('label="fall"')
                else:
                    edge_attrs.append('label="jump"')

            attr_str = ""
            if edge_attrs:
                attr_str = f' [{", ".join(edge_attrs)}]'

            lines.append(f'    B{block.id} -> B{succ.id}{attr_str};')

    lines.append('}')
    return '\n'.join(lines)


def _format_instruction_short(insn, mnemonic: str) -> str:
    """Format an instruction as a short string for DOT labels."""
    try:
        op = LuauOpcode(insn.opcode)
    except ValueError:
        return f"[{insn.pc}] {mnemonic}"

    parts = [f"[{insn.pc}] {mnemonic}"]

    if op in (LuauOpcode.LOADNIL, LuauOpcode.LOADB, LuauOpcode.LOADN, LuauOpcode.LOADK):
        parts.append(f"r{insn.a}")
    elif op == LuauOpcode.MOVE:
        parts.append(f"r{insn.a} <- r{insn.b}")
    elif op in (LuauOpcode.JUMP, LuauOpcode.JUMPBACK):
        target = insn.pc + 1 + insn.d
        parts.append(f"-> pc {target}")
    elif op == LuauOpcode.JUMPX:
        target = insn.pc + 1 + insn.e
        parts.append(f"-> pc {target}")
    elif op in (LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT):
        target = insn.pc + 1 + insn.d
        parts.append(f"r{insn.a} -> pc {target}")
    elif op in (LuauOpcode.JUMPIFEQ, LuauOpcode.JUMPIFLE, LuauOpcode.JUMPIFLT,
                LuauOpcode.JUMPIFNOTEQ, LuauOpcode.JUMPIFNOTLE, LuauOpcode.JUMPIFNOTLT):
        target = insn.pc + 1 + insn.d
        aux_reg = insn.aux if insn.aux is not None else "?"
        parts.append(f"r{insn.a} r{aux_reg} -> pc {target}")
    elif op in (LuauOpcode.FORNPREP, LuauOpcode.FORNLOOP):
        target = insn.pc + 1 + insn.d
        parts.append(f"r{insn.a} -> pc {target}")
    elif op in (LuauOpcode.FORGLOOP, LuauOpcode.FORGPREP, LuauOpcode.FORGPREP_INEXT,
                LuauOpcode.FORGPREP_NEXT):
        target = insn.pc + 1 + insn.d
        parts.append(f"r{insn.a} -> pc {target}")
    elif op == LuauOpcode.RETURN:
        if insn.b == 1:
            parts.append("(no values)")
        elif insn.b > 1:
            parts.append(f"r{insn.a}..r{insn.a + insn.b - 2}")
        else:
            parts.append(f"r{insn.a}.. (vararg)")
    elif op == LuauOpcode.CALL:
        parts.append(f"r{insn.a}({insn.b - 1} args, {insn.c - 1} ret)")

    return " ".join(parts)


def _escape_dot(s: str) -> str:
    """Escape special characters for DOT labels."""
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('{', '\\{')
    s = s.replace('}', '\\}')
    s = s.replace('<', '\\<')
    s = s.replace('>', '\\>')
    s = s.replace('|', '\\|')
    return s
