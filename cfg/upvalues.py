"""Upvalue analysis for SSA form.

Identifies captured upvalues (variables from enclosing scopes) and
determines their scopes and capture modes. This information is needed
to correctly decompile closures and upvalue references.

In Luau bytecode:
- GETUPVAL reads an upvalue from the enclosing scope
- SETUPVAL writes to an upvalue
- CLOSEUPVALS closes upvalues from a given register upward
- CAPTURE captures a local as an upvalue for a new closure
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from deserializer.opcodes import LuauOpcode

if TYPE_CHECKING:
    from ..function import FunctionCFG
    from deserializer.types import Proto


@dataclass
class UpvalueInfo:
    """Information about a single upvalue."""
    index: int  # upvalue index in the enclosing proto
    name: Optional[str] = None  # debug name if available
    # Blocks where this upvalue is read
    read_blocks: Set[int] = field(default_factory=set)
    # Blocks where this upvalue is written
    write_blocks: Set[int] = field(default_factory=set)
    # Whether this upvalue is ever written to
    is_mutable: bool = False
    # The register this upvalue was captured from (if known)
    source_register: Optional[int] = None


@dataclass
class CaptureInfo:
    """Information about a CAPTURE instruction for closure creation."""
    capture_type: int  # 0=VAL, 1=REF, 2=UPVAL
    register_or_upvalue: int  # register index (VAL/REF) or upvalue index (UPVAL)
    block_id: int
    pc: int


@dataclass
class UpvalueAnalysis:
    """Complete upvalue analysis results for a function."""
    # Upvalue info indexed by upvalue slot
    upvalues: Dict[int, UpvalueInfo] = field(default_factory=dict)
    # Captures for closures created in this function
    captures: List[CaptureInfo] = field(default_factory=list)
    # Registers that are captured as upvalues by child closures
    captured_registers: Set[int] = field(default_factory=set)
    # Blocks containing CLOSEUPVALS
    close_blocks: Dict[int, int] = field(default_factory=dict)  # block_id -> close_from_reg


def analyze_upvalues(
    cfg: 'FunctionCFG',
    proto: Optional['Proto'] = None,
) -> UpvalueAnalysis:
    """Analyze upvalue usage in a function CFG.

    Scans all instructions to find:
    1. GETUPVAL/SETUPVAL - upvalue reads and writes
    2. CAPTURE - upvalue captures for child closures
    3. CLOSEUPVALS - scope boundaries for upvalues
    4. NEWCLOSURE/DUPCLOSURE - closure creation sites

    Args:
        cfg: The function's control flow graph.
        proto: The proto for this function (provides upvalue names).

    Returns:
        UpvalueAnalysis with complete upvalue information.
    """
    analysis = UpvalueAnalysis()

    # Populate upvalue names from proto debug info
    if proto is not None:
        for idx, name in enumerate(proto.upvalue_names):
            analysis.upvalues[idx] = UpvalueInfo(index=idx, name=name)

    # Scan all blocks and instructions
    for block in cfg.blocks:
        for insn in block.instructions:
            try:
                opcode = LuauOpcode(insn.opcode)
            except ValueError:
                continue

            if opcode == LuauOpcode.GETUPVAL:
                # GETUPVAL A B: read upvalue B into register A
                uv_idx = insn.b
                if uv_idx not in analysis.upvalues:
                    analysis.upvalues[uv_idx] = UpvalueInfo(index=uv_idx)
                analysis.upvalues[uv_idx].read_blocks.add(block.id)

            elif opcode == LuauOpcode.SETUPVAL:
                # SETUPVAL A B: write register A to upvalue B
                uv_idx = insn.b
                if uv_idx not in analysis.upvalues:
                    analysis.upvalues[uv_idx] = UpvalueInfo(index=uv_idx)
                analysis.upvalues[uv_idx].write_blocks.add(block.id)
                analysis.upvalues[uv_idx].is_mutable = True

            elif opcode == LuauOpcode.CAPTURE:
                # CAPTURE type reg: capture a variable for a closure
                capture = CaptureInfo(
                    capture_type=insn.a,
                    register_or_upvalue=insn.b,
                    block_id=block.id,
                    pc=insn.pc,
                )
                analysis.captures.append(capture)

                # Track which registers are captured
                if insn.a in (0, 1):  # CAP_VALUE or CAP_REF
                    analysis.captured_registers.add(insn.b)

            elif opcode == LuauOpcode.CLOSEUPVALS:
                # CLOSEUPVALS A: close all upvalues from register A upward
                analysis.close_blocks[block.id] = insn.a

    return analysis


def find_upvalue_scopes(
    cfg: 'FunctionCFG',
    analysis: UpvalueAnalysis,
) -> Dict[int, Tuple[int, int]]:
    """Determine the scope (start_pc, end_pc) for each captured register.

    The scope of a captured register extends from its first definition
    to the CLOSEUPVALS instruction that closes it.

    Returns:
        Dict mapping register index to (start_pc, end_pc) tuple.
    """
    scopes: Dict[int, Tuple[int, int]] = {}

    for reg in analysis.captured_registers:
        reg_name = f"r{reg}"
        first_def_pc = None
        close_pc = None

        # Find first definition
        for block in cfg.blocks:
            if reg_name in block.defs:
                for insn in block.instructions:
                    try:
                        opcode = LuauOpcode(insn.opcode)
                    except ValueError:
                        continue
                    # Check if this instruction defines the register
                    from ..function import _get_insn_reads_writes
                    _, writes = _get_insn_reads_writes(insn, opcode)
                    if reg_name in writes:
                        if first_def_pc is None or insn.pc < first_def_pc:
                            first_def_pc = insn.pc
                        break

        # Find the CLOSEUPVALS that covers this register
        for block_id, close_from in analysis.close_blocks.items():
            if close_from <= reg:
                block = cfg.get_block_by_id(block_id)
                if block is not None:
                    for insn in block.instructions:
                        try:
                            if LuauOpcode(insn.opcode) == LuauOpcode.CLOSEUPVALS:
                                if close_pc is None or insn.pc > close_pc:
                                    close_pc = insn.pc
                        except ValueError:
                            continue

        if first_def_pc is not None:
            scopes[reg] = (first_def_pc, close_pc or cfg.blocks[-1].end_pc)

    return scopes


def get_capture_mode(capture: CaptureInfo) -> str:
    """Get a human-readable capture mode string."""
    modes = {0: "value", 1: "reference", 2: "upvalue"}
    return modes.get(capture.capture_type, f"unknown({capture.capture_type})")
