"""Luau bytecode lifter - transforms deserialized bytecode into an AST.

This is the core of the decompiler's lifting phase. It walks through the
instructions of each Proto, tracking register state, and produces
AST nodes that represent the original Lua source code.

The key concepts:
- Registers are tracked as a mapping from register number to Expression.
- "Pending expressions" (like TableConstructors built up across multiple
  instructions) are flushed to LocalDeclarations when they are first
  read by another instruction.
- For-loop structures are detected by FORGPREP_*/FORGLOOP instruction
  pairs, and the loop body is recursively lifted.
"""

from typing import Dict, List, Optional, Tuple, Any

from deserializer.types import Chunk, Proto, Instruction, Constant, ConstantType
from deserializer.opcodes import LuauOpcode, HAS_AUX

from ast.src.lib import Body, Expression, Statement
from ast.src.literal import NumberLiteral, StringLiteral, BoolLiteral, NilLiteral
from ast.src.local import Local, LocalRef
from ast.src.global_ref import GlobalRef
from ast.src.table import TableConstructor, TableField
from ast.src.call import FunctionCall, MethodCall, FunctionCallStatement
from ast.src.for_ import GenericFor, NumericFor
from ast.src.local_declarations import LocalDeclaration
from ast.src.return_ import Return
from ast.src.assign import Assignment
from ast.src.binary import BinaryOp
from ast.src.unary import UnaryOp
from ast.src.index import IndexExpression, DotExpression
from ast.src.closure import Closure
from ast.src.vararg import VarargExpression
from ast.src.if_ import IfStatement
from ast.src.while_ import WhileLoop
from ast.src.break_ import Break
from ast.src.continue_ import Continue

from .lib import (
    resolve_string,
    resolve_constant_string,
    resolve_import_name,
    constant_to_value,
)
from .instruction import get_jump_target, reads_register
from .op_code import BINARY_OPS, BINARY_K_OPS, COMPARE_OPS


class NameGenerator:
    """Generates meaningful variable names during lifting.

    Produces contextual names based on usage:
    - Tables get names like "t", "t2", "t3"
    - Generic for-loop variables get "k", "v" (for pairs) or "i", "v" (for ipairs)
    - Numeric for-loop variables get "i", "i2", etc.
    - Other locals get "v1", "v2", etc.
    """

    def __init__(self):
        self._used_names: set = set()
        self._var_counter: int = 0

    def _make_unique(self, base: str) -> str:
        """Ensure a name is unique by appending a number if needed."""
        if base not in self._used_names:
            self._used_names.add(base)
            return base
        n = 2
        while f"{base}{n}" in self._used_names:
            n += 1
        name = f"{base}{n}"
        self._used_names.add(name)
        return name

    def next_var(self) -> str:
        """Generate a generic variable name: v1, v2, ..."""
        self._var_counter += 1
        name = f"v{self._var_counter}"
        while name in self._used_names:
            self._var_counter += 1
            name = f"v{self._var_counter}"
        self._used_names.add(name)
        return name

    def table_var(self) -> str:
        """Generate a table variable name: t, t2, t3, ..."""
        return self._make_unique("t")

    def for_loop_vars(self, count: int, iterator_name: str = "") -> List[str]:
        """Generate for-loop variable names based on the iterator.

        Args:
            count: Number of loop variables.
            iterator_name: Name of the iterator function (e.g. "pairs", "ipairs").

        Returns:
            List of variable name strings.
        """
        if count == 2:
            if iterator_name == "ipairs":
                return [self._make_unique("i"), self._make_unique("v")]
            else:
                return [self._make_unique("k"), self._make_unique("v")]
        elif count == 1:
            return [self._make_unique("v")]
        else:
            return [self.next_var() for _ in range(count)]

    def numeric_for_var(self) -> str:
        """Generate a numeric for-loop variable name: i, i2, ..."""
        return self._make_unique("i")

    def func_param(self, index: int) -> str:
        """Generate a function parameter name."""
        param_names = ["a", "b", "c", "d", "e", "f"]
        if index < len(param_names):
            return self._make_unique(param_names[index])
        return self.next_var()

    def reserve(self, name: str):
        """Reserve a name so it won't be generated."""
        self._used_names.add(name)

    def use_name(self, name: str) -> str:
        """Use a specific name (e.g. from debug info), ensuring uniqueness."""
        return self._make_unique(name)


class _PendingExpression:
    """Tracks an expression in a register that hasn't been emitted as a statement yet.

    When instructions build up complex expressions across multiple steps
    (e.g. DUPTABLE + multiple SETTABLEKS), the expression is "pending"
    in a register until it's consumed by another instruction. At that point,
    we flush it to a LocalDeclaration.
    """

    def __init__(self, expr: Expression, reg: int, name_hint: Optional[str] = None):
        self.expr = expr
        self.reg = reg
        self.name_hint = name_hint


class _ForCallInfo:
    """Stores information about a CALL that sets up a for-loop iterator.

    Before a FORGPREP_NEXT instruction, a CALL writes iterator/state/control
    to registers A, A+1, A+2. We save the call expression and the function
    expression so we can reconstruct the iterator for the GenericFor AST node.
    """

    def __init__(self, call_expr: Expression, func_expr: Expression, base_reg: int):
        self.call_expr = call_expr
        self.func_expr = func_expr
        self.base_reg = base_reg


class _NamecallInfo:
    """Stores info from a NAMECALL instruction for the subsequent CALL.

    NAMECALL sets up a method call by storing the object and method name.
    The following CALL instruction uses this to emit a MethodCall (colon syntax)
    instead of a regular FunctionCall.
    """

    def __init__(self, obj_expr: Expression, method_name: str):
        self.obj_expr = obj_expr
        self.method_name = method_name


class Lifter:
    """Lifts deserialized Luau bytecode into an AST.

    The lifter processes instructions sequentially, maintaining a register
    state machine that tracks what expression each register currently holds.
    As it encounters instructions, it builds AST nodes and emits statements.

    Usage:
        chunk = deserialize(bytecode, encode_key)
        lifter = Lifter(chunk)
        body = lifter.lift()
        print(body)  # prints formatted Lua source
    """

    def __init__(self, chunk: Chunk):
        self.chunk = chunk
        self.name_gen = NameGenerator()
        self._current_proto: Optional[Proto] = None
        self._current_pc: int = 0

    def lift(self) -> Body:
        """Lift the main proto into an AST Body.

        Returns:
            A Body containing the top-level statements of the bytecode.
        """
        proto = self.chunk.protos[self.chunk.main_proto]
        stmts = self._lift_block(proto, 0, len(proto.instructions), is_main=True)
        return Body(statements=stmts)

    def lift_proto(self, proto: Proto, is_main: bool = False) -> List[Statement]:
        """Lift all instructions in a proto into a list of statements.

        Args:
            proto: The proto to lift.
            is_main: Whether this is the main/top-level proto.

        Returns:
            List of AST Statement nodes.
        """
        return self._lift_block(proto, 0, len(proto.instructions), is_main=is_main)

    def _lift_block(
        self,
        proto: Proto,
        start_idx: int,
        end_idx: int,
        is_main: bool = False,
        registers: Optional[Dict[int, Expression]] = None,
        locals_map: Optional[Dict[int, Local]] = None,
        pending: Optional[Dict[int, _PendingExpression]] = None,
        for_call_infos: Optional[Dict[int, _ForCallInfo]] = None,
    ) -> List[Statement]:
        """Lift a range of instructions into a list of statements.

        This is the core instruction processing loop. It walks instructions
        from start_idx to end_idx, building up register state and emitting
        statements as it goes.

        Args:
            proto: The proto containing the instructions.
            start_idx: Index into proto.instructions to start at (inclusive).
            end_idx: Index into proto.instructions to end at (exclusive).
            is_main: Whether this is the main/top-level proto.
            registers: Pre-initialized register state (or None for fresh).
            locals_map: Pre-initialized locals mapping (or None for fresh).
            pending: Pre-initialized pending expressions (or None for fresh).
            for_call_infos: Pre-initialized for-call info (or None for fresh).

        Returns:
            List of AST Statement nodes.
        """
        if registers is None:
            registers = {}
        if locals_map is None:
            locals_map = {}
        if pending is None:
            pending = {}
        if for_call_infos is None:
            for_call_infos = {}

        namecall_infos: Dict[int, _NamecallInfo] = {}
        stmts: List[Statement] = []
        idx = start_idx

        while idx < end_idx:
            insn = proto.instructions[idx]
            op = insn.opcode
            self._current_proto = proto
            self._current_pc = insn.pc

            try:
                luau_op = LuauOpcode(op)
            except ValueError:
                # Unknown opcode, skip
                idx += 1
                continue

            # ---------------------------------------------------------------
            # PREPVARARGS (65) - marks a vararg function, skip
            # ---------------------------------------------------------------
            if luau_op == LuauOpcode.PREPVARARGS:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # NOP (0), BREAK (1) - skip
            # ---------------------------------------------------------------
            elif luau_op in (LuauOpcode.NOP, LuauOpcode.BREAK):
                idx += 1
                continue

            # ---------------------------------------------------------------
            # LOADNIL (2) - R[A] = nil
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.LOADNIL:
                registers[insn.a] = NilLiteral()
                idx += 1
                continue

            # ---------------------------------------------------------------
            # LOADB (3) - R[A] = (bool)B; if C, skip next instruction
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.LOADB:
                registers[insn.a] = BoolLiteral(value=bool(insn.b))
                if insn.c:
                    idx += 2  # skip next instruction
                else:
                    idx += 1
                continue

            # ---------------------------------------------------------------
            # LOADN (4) - R[A] = D (as number)
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.LOADN:
                registers[insn.a] = NumberLiteral(value=float(insn.d))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # LOADK (5) - R[A] = K[D]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.LOADK:
                pending.pop(insn.a, None)  # Clear any stale pending for this register
                expr = self._constant_to_expression(proto, insn.d)
                registers[insn.a] = expr
                idx += 1
                continue

            # ---------------------------------------------------------------
            # MOVE (6) - R[A] = R[B]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.MOVE:
                # Flush pending expression if B holds one
                self._flush_if_pending(
                    insn.b, registers, locals_map, pending, stmts
                )

                # If B has a local, reference it
                if insn.b in locals_map:
                    registers[insn.a] = LocalRef(local=locals_map[insn.b])
                elif insn.b in registers:
                    registers[insn.a] = registers[insn.b]
                else:
                    registers[insn.a] = NilLiteral()
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETGLOBAL (7) - R[A] = _env[K[AUX]]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETGLOBAL:
                name = resolve_constant_string(self.chunk, proto, insn.aux)
                registers[insn.a] = GlobalRef(name=name)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SETGLOBAL (8) - _env[K[AUX]] = R[A]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SETGLOBAL:
                name = resolve_constant_string(self.chunk, proto, insn.aux)
                if insn.a in pending:
                    # Consume pending expression directly — no need for a temp local
                    pend = pending.pop(insn.a)
                    value = pend.expr
                    # Future reads of this register get the global name
                    registers[insn.a] = GlobalRef(name=name)
                else:
                    self._flush_if_pending(insn.a, registers, locals_map, pending, stmts)
                    value = self._get_reg_expr(insn.a, registers, locals_map)
                stmts.append(Assignment(
                    targets=[GlobalRef(name=name)],
                    values=[value],
                ))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETUPVAL (9) - R[A] = UpValue[B]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETUPVAL:
                # For now, represent upvalues as globals with a placeholder name
                uv_name = f"upval_{insn.b}"
                if insn.b < len(proto.upvalue_names):
                    uv_name = proto.upvalue_names[insn.b]
                registers[insn.a] = GlobalRef(name=uv_name)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SETUPVAL (10) - UpValue[B] = R[A]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SETUPVAL:
                uv_name = f"upval_{insn.b}"
                if insn.b < len(proto.upvalue_names):
                    uv_name = proto.upvalue_names[insn.b]
                self._flush_if_pending(insn.a, registers, locals_map, pending, stmts)
                value = self._get_reg_expr(insn.a, registers, locals_map)
                stmts.append(Assignment(
                    targets=[GlobalRef(name=uv_name)],
                    values=[value],
                ))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # CLOSEUPVALS (11) - close upvalues >= R[A]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.CLOSEUPVALS:
                # Internal VM operation, skip
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETIMPORT (12) - R[A] = import(K[D], AUX)
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETIMPORT:
                import_id = insn.aux
                name = resolve_import_name(self.chunk, proto, import_id)
                # For multi-part imports (e.g. "math.floor"), build a DotExpression
                parts = name.split(".")
                if len(parts) == 1:
                    registers[insn.a] = GlobalRef(name=parts[0])
                elif len(parts) == 2:
                    registers[insn.a] = DotExpression(
                        table=GlobalRef(name=parts[0]),
                        field_name=parts[1],
                    )
                else:
                    # 3+ parts: chain DotExpressions
                    expr = GlobalRef(name=parts[0])
                    for part in parts[1:]:
                        expr = DotExpression(table=expr, field_name=part)
                    registers[insn.a] = expr
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETTABLE (13) - R[A] = R[B][R[C]]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETTABLE:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                self._flush_if_pending(insn.c, registers, locals_map, pending, stmts)
                table_expr = self._get_reg_expr(insn.b, registers, locals_map)
                key_expr = self._get_reg_expr(insn.c, registers, locals_map)
                registers[insn.a] = IndexExpression(table=table_expr, key=key_expr)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SETTABLE (14) - R[B][R[C]] = R[A]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SETTABLE:
                self._flush_if_pending(insn.a, registers, locals_map, pending, stmts)
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                self._flush_if_pending(insn.c, registers, locals_map, pending, stmts)
                table_expr = self._get_reg_expr(insn.b, registers, locals_map)
                key_expr = self._get_reg_expr(insn.c, registers, locals_map)
                value_expr = self._get_reg_expr(insn.a, registers, locals_map)
                stmts.append(Assignment(
                    targets=[IndexExpression(table=table_expr, key=key_expr)],
                    values=[value_expr],
                ))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETTABLEKS (15) - R[A] = R[B][K[AUX]]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETTABLEKS:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                table_expr = self._get_reg_expr(insn.b, registers, locals_map)
                key_name = resolve_constant_string(self.chunk, proto, insn.aux)
                registers[insn.a] = DotExpression(table=table_expr, field_name=key_name)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SETTABLEKS (16) - R[B][K[AUX]] = R[A]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SETTABLEKS:
                key_name = resolve_constant_string(self.chunk, proto, insn.aux)

                # If R[B] is a pending TableConstructor, append to it
                if insn.b in pending and isinstance(pending[insn.b].expr, TableConstructor):
                    table_ctor = pending[insn.b].expr
                    value_expr = registers.get(insn.a, NilLiteral())
                    table_ctor.fields.append(
                        TableField(
                            key=StringLiteral(value=key_name),
                            value=value_expr,
                        )
                    )
                    # Update the register to the updated table
                    registers[insn.b] = table_ctor
                else:
                    # Emit as an assignment: table.key = value
                    self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                    self._flush_if_pending(insn.a, registers, locals_map, pending, stmts)
                    table_expr = self._get_reg_expr(insn.b, registers, locals_map)
                    value_expr = self._get_reg_expr(insn.a, registers, locals_map)
                    stmts.append(Assignment(
                        targets=[DotExpression(table=table_expr, field_name=key_name)],
                        values=[value_expr],
                    ))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETTABLEN (17) - R[A] = R[B][C+1]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETTABLEN:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                table_expr = self._get_reg_expr(insn.b, registers, locals_map)
                key_expr = NumberLiteral(value=float(insn.c + 1))
                registers[insn.a] = IndexExpression(table=table_expr, key=key_expr)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SETTABLEN (18) - R[B][C+1] = R[A]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SETTABLEN:
                self._flush_if_pending(insn.a, registers, locals_map, pending, stmts)
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                table_expr = self._get_reg_expr(insn.b, registers, locals_map)
                key_expr = NumberLiteral(value=float(insn.c + 1))
                value_expr = self._get_reg_expr(insn.a, registers, locals_map)
                stmts.append(Assignment(
                    targets=[IndexExpression(table=table_expr, key=key_expr)],
                    values=[value_expr],
                ))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # NEWTABLE (53) - R[A] = {} (with size hints)
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.NEWTABLE:
                table_ctor = TableConstructor(fields=[])
                registers[insn.a] = table_ctor
                pending[insn.a] = _PendingExpression(table_ctor, insn.a)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # DUPTABLE (54) - R[A] = {} (table with template keys)
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.DUPTABLE:
                table_ctor = TableConstructor(fields=[])
                registers[insn.a] = table_ctor
                pending[insn.a] = _PendingExpression(table_ctor, insn.a)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SETLIST (55) - R[A][AUX+i] = R[B+i], 1 <= i <= C
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SETLIST:
                # If R[A] is a pending TableConstructor, append array elements
                if insn.a in pending and isinstance(pending[insn.a].expr, TableConstructor):
                    table_ctor = pending[insn.a].expr
                    count = insn.c - 1 if insn.c > 0 else 0
                    for i in range(count):
                        val = registers.get(insn.b + i, NilLiteral())
                        table_ctor.fields.append(TableField(key=None, value=val))
                    registers[insn.a] = table_ctor
                idx += 1
                continue

            # ---------------------------------------------------------------
            # NEWCLOSURE (19) - R[A] = closure(proto[D])
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.NEWCLOSURE:
                child_proto_idx = proto.child_protos[insn.d] if insn.d < len(proto.child_protos) else insn.d
                child_proto = self.chunk.protos[child_proto_idx]
                closure_expr = self._lift_closure(child_proto)
                if child_proto.line_defined > 0:
                    closure_expr.line_defined = child_proto.line_defined
                registers[insn.a] = closure_expr
                # Use function debug name as hint for the variable name
                func_name = None
                if child_proto.debug_name_idx > 0:
                    func_name = resolve_string(self.chunk, child_proto.debug_name_idx)
                if func_name:
                    closure_expr.debug_name = func_name
                pending[insn.a] = _PendingExpression(closure_expr, insn.a, name_hint=func_name)
                # Process CAPTURE instructions that follow
                idx += 1
                capture_idx = 0
                while idx < end_idx:
                    next_insn = proto.instructions[idx]
                    if LuauOpcode(next_insn.opcode) == LuauOpcode.CAPTURE:
                        # CAPTURE A B: A=type (0=val, 1=ref, 2=upval), B=source
                        cap_type = next_insn.a
                        # Get name from child proto's upvalue list
                        if capture_idx < len(child_proto.upvalue_names):
                            uv_name = child_proto.upvalue_names[capture_idx]
                        else:
                            uv_name = f"upval_{capture_idx}"
                        # 0=CAPTURE_VAL (copy), 1=CAPTURE_REF (ref), 2=CAPTURE_UPVAL (ref)
                        uv_type = "copy" if cap_type == 0 else "ref"
                        closure_expr.upvalue_captures.append((uv_name, uv_type))
                        capture_idx += 1
                        idx += 1
                    else:
                        break
                continue

            # ---------------------------------------------------------------
            # DUPCLOSURE (64) - R[A] = closure(K[D])
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.DUPCLOSURE:
                k = proto.constants[insn.d]
                if k.type == ConstantType.CLOSURE:
                    child_proto = self.chunk.protos[k.value_closure]
                    closure_expr = self._lift_closure(child_proto)
                    if child_proto.line_defined > 0:
                        closure_expr.line_defined = child_proto.line_defined
                    registers[insn.a] = closure_expr
                    # Use function debug name as hint
                    func_name = None
                    if child_proto.debug_name_idx > 0:
                        func_name = resolve_string(self.chunk, child_proto.debug_name_idx)
                    if func_name:
                        closure_expr.debug_name = func_name
                    pending[insn.a] = _PendingExpression(closure_expr, insn.a, name_hint=func_name)
                else:
                    registers[insn.a] = NilLiteral()
                # Process CAPTURE instructions
                idx += 1
                capture_idx = 0
                # Only read captures if we have a valid closure
                cap_closure = closure_expr if k.type == ConstantType.CLOSURE else None
                while idx < end_idx:
                    next_insn = proto.instructions[idx]
                    if LuauOpcode(next_insn.opcode) == LuauOpcode.CAPTURE:
                        if cap_closure is not None:
                            cap_type = next_insn.a
                            if capture_idx < len(child_proto.upvalue_names):
                                uv_name = child_proto.upvalue_names[capture_idx]
                            else:
                                uv_name = f"upval_{capture_idx}"
                            uv_type = "copy" if cap_type == 0 else "ref"
                            cap_closure.upvalue_captures.append((uv_name, uv_type))
                            capture_idx += 1
                        idx += 1
                    else:
                        break
                continue

            # ---------------------------------------------------------------
            # NAMECALL (20) - R[A+1] = R[B]; R[A] = R[B][K[AUX]]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.NAMECALL:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                obj_expr = self._get_reg_expr(insn.b, registers, locals_map)
                method_name = resolve_constant_string(self.chunk, proto, insn.aux)
                # R[A+1] = the object (self), R[A] = the method
                registers[insn.a + 1] = obj_expr
                registers[insn.a] = DotExpression(table=obj_expr, field_name=method_name)
                # Mark for the upcoming CALL to use colon syntax
                namecall_infos[insn.a] = _NamecallInfo(
                    obj_expr=obj_expr, method_name=method_name
                )
                idx += 1
                continue

            # ---------------------------------------------------------------
            # CALL (21) - R[A], ... = R[A](R[A+1], ..., R[A+B-1])
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.CALL:
                func_reg = insn.a
                nargs = insn.b - 1 if insn.b > 0 else 0
                nresults = insn.c - 1 if insn.c > 0 else 0

                # Check if this CALL was set up by NAMECALL (method call)
                nc_info = namecall_infos.pop(func_reg, None)

                if nc_info is not None:
                    # Method call: obj:method(args) — skip self (R[A+1])
                    for r in range(func_reg + 2, func_reg + 1 + nargs):
                        self._flush_if_pending(r, registers, locals_map, pending, stmts)
                    method_args = []
                    for i in range(1, nargs):  # start from 1 to skip self
                        arg_reg = func_reg + 1 + i
                        method_args.append(self._get_reg_expr(arg_reg, registers, locals_map))
                    call = MethodCall(
                        object=nc_info.obj_expr,
                        method=nc_info.method_name,
                        args=method_args,
                    )
                    # Save for-call info for potential for-loop
                    for_call_infos[func_reg] = _ForCallInfo(
                        call_expr=call,
                        func_expr=GlobalRef(name=nc_info.method_name),
                        base_reg=func_reg,
                    )
                else:
                    # Regular function call
                    for r in range(func_reg + 1, func_reg + 1 + nargs):
                        self._flush_if_pending(r, registers, locals_map, pending, stmts)
                    func_expr = registers.get(func_reg, NilLiteral())
                    args = []
                    for i in range(nargs):
                        arg_reg = func_reg + 1 + i
                        args.append(self._get_reg_expr(arg_reg, registers, locals_map))
                    call = FunctionCall(func=func_expr, args=args)
                    # Save for-call info for potential for-loop
                    for_call_infos[func_reg] = _ForCallInfo(
                        call_expr=call,
                        func_expr=func_expr,
                        base_reg=func_reg,
                    )

                if nresults == 0:
                    stmts.append(FunctionCallStatement(call=call))
                else:
                    registers[func_reg] = call
                    pending[func_reg] = _PendingExpression(call, func_reg)
                    for i in range(1, nresults):
                        registers[func_reg + i] = NilLiteral()

                idx += 1
                continue

            # ---------------------------------------------------------------
            # RETURN (22) - return R[A], ..., R[A+B-2]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.RETURN:
                if insn.b == 1:
                    # Return nothing
                    if not is_main:
                        stmts.append(Return(values=[]))
                    else:
                        # For main chunk, emit empty return (formatter skips it at top level)
                        stmts.append(Return(values=[]))
                elif insn.b > 1:
                    nvals = insn.b - 1
                    values = []
                    for i in range(nvals):
                        r = insn.a + i
                        self._flush_if_pending(r, registers, locals_map, pending, stmts)
                        values.append(self._get_reg_expr(r, registers, locals_map))
                    stmts.append(Return(values=values))
                else:
                    # B == 0: return all from A to top of stack (vararg)
                    stmts.append(Return(values=[]))
                idx += 1
                continue

            # ---------------------------------------------------------------
            # JUMP (23) - pc += D
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.JUMP:
                # Unconditional jump - used for control flow structures.
                # At this stage we just skip it; proper control flow recovery
                # is handled by higher-level structure analysis.
                idx += 1
                continue

            # ---------------------------------------------------------------
            # JUMPBACK (24) - pc += D (backwards jump, loop)
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.JUMPBACK:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # JUMPIF (25) / JUMPIFNOT (26) - conditional jumps
            # ---------------------------------------------------------------
            elif luau_op in (LuauOpcode.JUMPIF, LuauOpcode.JUMPIFNOT):
                jump_target_pc = get_jump_target(insn)
                target_idx = self._pc_to_idx(proto, jump_target_pc)
                if target_idx is None or target_idx > end_idx:
                    target_idx = end_idx

                # Backward jump = loop construct, skip for now
                if target_idx <= idx:
                    idx += 1
                    continue

                cond_expr = self._get_reg_expr(insn.a, registers, locals_map)

                if luau_op == LuauOpcode.JUMPIFNOT:
                    condition = cond_expr
                else:
                    condition = UnaryOp(op="not", operand=cond_expr)

                if_stmt, resume_idx = self._build_if_statement(
                    proto, condition, idx, target_idx, end_idx,
                    registers, locals_map, pending, for_call_infos,
                )
                stmts.append(if_stmt)
                idx = resume_idx
                continue

            # ---------------------------------------------------------------
            # Comparison jumps (27-32)
            # ---------------------------------------------------------------
            elif luau_op in COMPARE_OPS:
                jump_target_pc = get_jump_target(insn)
                target_idx = self._pc_to_idx(proto, jump_target_pc)
                if target_idx is None or target_idx > end_idx:
                    target_idx = end_idx

                # Backward jump = loop construct, skip for now
                if target_idx <= idx:
                    idx += 1
                    continue

                op_str = COMPARE_OPS[luau_op]
                left = self._get_reg_expr(insn.a, registers, locals_map)
                right_reg = insn.aux & 0xFF if insn.aux is not None else 0
                right = self._get_reg_expr(right_reg, registers, locals_map)
                condition = BinaryOp(op=op_str, left=left, right=right)

                if_stmt, resume_idx = self._build_if_statement(
                    proto, condition, idx, target_idx, end_idx,
                    registers, locals_map, pending, for_call_infos,
                )
                stmts.append(if_stmt)
                idx = resume_idx
                continue

            # ---------------------------------------------------------------
            # ADD..POW (33-38) - R[A] = R[B] op R[C]
            # ---------------------------------------------------------------
            elif luau_op in BINARY_OPS:
                op_str = BINARY_OPS[luau_op]
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                self._flush_if_pending(insn.c, registers, locals_map, pending, stmts)
                left = self._get_reg_expr(insn.b, registers, locals_map)
                right = self._get_reg_expr(insn.c, registers, locals_map)
                registers[insn.a] = BinaryOp(op=op_str, left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # ADDK..POWK (39-44), IDIVK (82) - R[A] = R[B] op K[C]
            # ---------------------------------------------------------------
            elif luau_op in BINARY_K_OPS:
                op_str = BINARY_K_OPS[luau_op]
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                left = self._get_reg_expr(insn.b, registers, locals_map)
                right = self._constant_to_expression(proto, insn.c)
                registers[insn.a] = BinaryOp(op=op_str, left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # AND (45) - R[A] = R[B] and R[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.AND:
                left = self._get_reg_expr(insn.b, registers, locals_map)
                right = self._get_reg_expr(insn.c, registers, locals_map)
                registers[insn.a] = BinaryOp(op="and", left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # OR (46) - R[A] = R[B] or R[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.OR:
                left = self._get_reg_expr(insn.b, registers, locals_map)
                right = self._get_reg_expr(insn.c, registers, locals_map)
                registers[insn.a] = BinaryOp(op="or", left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # ANDK (47) - R[A] = R[B] and K[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.ANDK:
                left = self._get_reg_expr(insn.b, registers, locals_map)
                right = self._constant_to_expression(proto, insn.c)
                registers[insn.a] = BinaryOp(op="and", left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # ORK (48) - R[A] = R[B] or K[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.ORK:
                left = self._get_reg_expr(insn.b, registers, locals_map)
                right = self._constant_to_expression(proto, insn.c)
                registers[insn.a] = BinaryOp(op="or", left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # CONCAT (49) - R[A] = R[B] .. ... .. R[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.CONCAT:
                # Build a chain of ".." binary ops
                exprs = []
                for r in range(insn.b, insn.c + 1):
                    self._flush_if_pending(r, registers, locals_map, pending, stmts)
                    exprs.append(self._get_reg_expr(r, registers, locals_map))
                if len(exprs) == 1:
                    registers[insn.a] = exprs[0]
                else:
                    result = exprs[0]
                    for e in exprs[1:]:
                        result = BinaryOp(op="..", left=result, right=e)
                    registers[insn.a] = result
                idx += 1
                continue

            # ---------------------------------------------------------------
            # NOT (50) - R[A] = not R[B]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.NOT:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                operand = self._get_reg_expr(insn.b, registers, locals_map)
                registers[insn.a] = UnaryOp(op="not", operand=operand)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # MINUS (51) - R[A] = -R[B]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.MINUS:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                operand = self._get_reg_expr(insn.b, registers, locals_map)
                registers[insn.a] = UnaryOp(op="-", operand=operand)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # LENGTH (52) - R[A] = #R[B]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.LENGTH:
                self._flush_if_pending(insn.b, registers, locals_map, pending, stmts)
                operand = self._get_reg_expr(insn.b, registers, locals_map)
                registers[insn.a] = UnaryOp(op="#", operand=operand)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # FORNPREP (56) - prepare numeric for loop
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.FORNPREP:
                # R[A] = start, R[A+1] = limit, R[A+2] = step
                # D = jump offset to FORNLOOP
                loop_target_pc = get_jump_target(insn)
                loop_idx = self._pc_to_idx(proto, loop_target_pc)
                if loop_idx is None:
                    idx += 1
                    continue

                # Create the loop variable
                var_name = self.name_gen.numeric_for_var()
                loop_var = Local(name=var_name, reg=insn.a + 2)

                start_expr = self._get_reg_expr(insn.a, registers, locals_map)
                stop_expr = self._get_reg_expr(insn.a + 1, registers, locals_map)
                step_expr = self._get_reg_expr(insn.a + 2, registers, locals_map)

                # Check if step is 1 (default)
                step = None
                if not (isinstance(step_expr, NumberLiteral) and step_expr.value == 1.0):
                    step = step_expr

                # Lift the loop body (from after FORNPREP to FORNLOOP exclusive)
                body_regs = dict(registers)
                body_locals = dict(locals_map)
                body_locals[insn.a + 2] = loop_var
                body_regs[insn.a + 2] = LocalRef(local=loop_var)

                body_stmts = self._lift_block(
                    proto, idx + 1, loop_idx,
                    registers=body_regs,
                    locals_map=body_locals,
                    pending=dict(pending),
                    for_call_infos=dict(for_call_infos),
                )

                stmts.append(NumericFor(
                    var=loop_var,
                    start=start_expr,
                    stop=stop_expr,
                    step=step,
                    body=Body(statements=body_stmts),
                ))

                # Skip past the FORNLOOP instruction
                idx = loop_idx + 1
                continue

            # ---------------------------------------------------------------
            # FORNLOOP (57) - numeric for loop back edge
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.FORNLOOP:
                # Handled by FORNPREP, skip
                idx += 1
                continue

            # ---------------------------------------------------------------
            # FORGPREP_NEXT (61), FORGPREP_INEXT (59), FORGPREP (76)
            # Generic for loop preparation
            # ---------------------------------------------------------------
            elif luau_op in (LuauOpcode.FORGPREP_NEXT, LuauOpcode.FORGPREP_INEXT,
                             LuauOpcode.FORGPREP):
                base_reg = insn.a  # Iterator base register

                # Find the FORGLOOP instruction this pairs with
                forgloop_target_pc = get_jump_target(insn)
                forgloop_idx = self._pc_to_idx(proto, forgloop_target_pc)

                if forgloop_idx is None:
                    idx += 1
                    continue

                forgloop_insn = proto.instructions[forgloop_idx]

                # Get number of loop variables from FORGLOOP's AUX
                nloop_vars = (forgloop_insn.aux & 0xFF) if forgloop_insn.aux is not None else 2

                # Determine the iterator function name for naming variables
                iterator_name = ""
                call_info = for_call_infos.get(base_reg)
                if call_info is not None:
                    func = call_info.func_expr
                    if isinstance(func, GlobalRef):
                        iterator_name = func.name
                    elif isinstance(func, DotExpression):
                        iterator_name = func.field_name

                # Create loop variable Locals
                var_names = self.name_gen.for_loop_vars(nloop_vars, iterator_name)
                loop_vars = []
                body_regs = dict(registers)
                body_locals = dict(locals_map)

                for i, vname in enumerate(var_names):
                    reg = base_reg + 3 + i
                    local = Local(name=vname, reg=reg)
                    loop_vars.append(local)
                    body_locals[reg] = local
                    body_regs[reg] = LocalRef(local=local)

                # Build the iterators list for GenericFor.
                # The iterators are what appears after "in" in "for k, v in ..."
                # This should be the original call expression, e.g. pairs(t)
                iterators: List[Expression] = []
                if call_info is not None:
                    iterators = [call_info.call_expr]
                else:
                    # Fallback: use whatever is in the base registers
                    for r in range(base_reg, base_reg + 3):
                        if r in registers:
                            iterators.append(registers[r])

                # Lift the loop body: from (idx+1) to forgloop_idx
                body_stmts = self._lift_block(
                    proto, idx + 1, forgloop_idx,
                    registers=body_regs,
                    locals_map=body_locals,
                    pending=dict(pending),
                    for_call_infos=dict(for_call_infos),
                )

                stmts.append(GenericFor(
                    vars=loop_vars,
                    iterators=iterators,
                    body=Body(statements=body_stmts),
                ))

                # Skip past the FORGLOOP instruction
                idx = forgloop_idx + 1
                continue

            # ---------------------------------------------------------------
            # FORGLOOP (58) - generic for loop back edge
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.FORGLOOP:
                # Handled by FORGPREP, skip
                idx += 1
                continue

            # ---------------------------------------------------------------
            # GETVARARGS (63) - R[A], ..., R[A+B-2] = ...
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.GETVARARGS:
                if insn.b == 1:
                    # Zero results requested
                    pass
                elif insn.b > 1:
                    nvals = insn.b - 1
                    for i in range(nvals):
                        registers[insn.a + i] = VarargExpression()
                else:
                    # B == 0: variable number of results
                    registers[insn.a] = VarargExpression()
                idx += 1
                continue

            # ---------------------------------------------------------------
            # FASTCALL (68), FASTCALL1 (73), FASTCALL2 (74) - skip
            # These are optimization hints; the actual CALL follows
            # ---------------------------------------------------------------
            elif luau_op in (LuauOpcode.FASTCALL, LuauOpcode.FASTCALL1,
                             LuauOpcode.FASTCALL2, LuauOpcode.FASTCALL2K):
                idx += 1
                continue

            # ---------------------------------------------------------------
            # CAPTURE (70) - capture upvalue for closure
            # Handled by NEWCLOSURE/DUPCLOSURE
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.CAPTURE:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # SUBRK (71) - R[A] = K[B] - R[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.SUBRK:
                left = self._constant_to_expression(proto, insn.b)
                self._flush_if_pending(insn.c, registers, locals_map, pending, stmts)
                right = self._get_reg_expr(insn.c, registers, locals_map)
                registers[insn.a] = BinaryOp(op="-", left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # DIVRK (72) - R[A] = K[B] / R[C]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.DIVRK:
                left = self._constant_to_expression(proto, insn.b)
                self._flush_if_pending(insn.c, registers, locals_map, pending, stmts)
                right = self._get_reg_expr(insn.c, registers, locals_map)
                registers[insn.a] = BinaryOp(op="/", left=left, right=right)
                idx += 1
                continue

            # ---------------------------------------------------------------
            # LOADKX (66) - R[A] = K[AUX]
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.LOADKX:
                pending.pop(insn.a, None)  # Clear any stale pending for this register
                expr = self._constant_to_expression(proto, insn.aux)
                registers[insn.a] = expr
                idx += 1
                continue

            # ---------------------------------------------------------------
            # JUMPX (67) - long unconditional jump
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.JUMPX:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # JUMPXEQKNIL (77) - jump if R[A] == nil (or ~= nil if NOT flag)
            # JUMPXEQKB (78) - jump if R[A] == bool (or ~= if NOT flag)
            # JUMPXEQKN (79) - jump if R[A] == K[idx] (number)
            # JUMPXEQKS (80) - jump if R[A] == K[idx] (string)
            # AUX bit 31 = NOT flag; bits 0-30 = value/index
            # ---------------------------------------------------------------
            elif luau_op in (LuauOpcode.JUMPXEQKNIL, LuauOpcode.JUMPXEQKB,
                             LuauOpcode.JUMPXEQKN, LuauOpcode.JUMPXEQKS):
                jump_target_pc = get_jump_target(insn)
                target_idx = self._pc_to_idx(proto, jump_target_pc)
                if target_idx is None or target_idx > end_idx:
                    target_idx = end_idx

                # Backward jump = loop construct, skip for now
                if target_idx <= idx:
                    idx += 1
                    continue

                aux = insn.aux if insn.aux is not None else 0
                not_flag = bool(aux & 0x80000000)
                aux_val = aux & 0x7FFFFFFF

                left = self._get_reg_expr(insn.a, registers, locals_map)

                if luau_op == LuauOpcode.JUMPXEQKNIL:
                    right = NilLiteral()
                elif luau_op == LuauOpcode.JUMPXEQKB:
                    right = BoolLiteral(value=bool(aux_val & 1))
                elif luau_op == LuauOpcode.JUMPXEQKN:
                    right = self._constant_to_expression(proto, aux_val)
                else:  # JUMPXEQKS
                    right = self._constant_to_expression(proto, aux_val)

                # Then-body is fall-through: negate the jump condition
                # NOT=0: jump if ==, then-body is ~=
                # NOT=1: jump if ~=, then-body is ==
                op_str = "==" if not_flag else "~="
                condition = BinaryOp(op=op_str, left=left, right=right)

                if_stmt, resume_idx = self._build_if_statement(
                    proto, condition, idx, target_idx, end_idx,
                    registers, locals_map, pending, for_call_infos,
                )
                stmts.append(if_stmt)
                idx = resume_idx
                continue

            # ---------------------------------------------------------------
            # COVERAGE (69) - skip
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.COVERAGE:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # DEP_FORGLOOP_INEXT (60) - deprecated, skip
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.DEP_FORGLOOP_INEXT:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # NATIVECALL (62) - skip
            # ---------------------------------------------------------------
            elif luau_op == LuauOpcode.NATIVECALL:
                idx += 1
                continue

            # ---------------------------------------------------------------
            # Unknown/unhandled opcode
            # ---------------------------------------------------------------
            else:
                idx += 1
                continue

        return stmts

    def _build_if_statement(
        self,
        proto: Proto,
        condition: Expression,
        idx: int,
        target_idx: int,
        end_idx: int,
        registers: Dict[int, Expression],
        locals_map: Dict[int, Local],
        pending: Dict[int, _PendingExpression],
        for_call_infos: Dict[int, _ForCallInfo],
    ) -> Tuple[IfStatement, int]:
        """Build an IfStatement with else-detection and elseif-flattening.

        Checks if the instruction before target_idx is an unconditional JUMP.
        If so, the JUMP skips the else-body, and we lift both branches.
        Also flattens nested if-in-else into elseif chains.

        Args:
            proto: The proto containing the instructions.
            condition: The condition expression for the if-statement.
            idx: Index of the conditional jump instruction.
            target_idx: Index of the jump target (start of else or merge point).
            end_idx: End of the current block being lifted.
            registers, locals_map, pending, for_call_infos: Current state.

        Returns:
            (if_stmt, resume_idx) where resume_idx is where the outer loop
            should continue processing.
        """
        has_else = False
        else_end_idx = None

        # Check for else branch: look for JUMP right before the jump target
        if target_idx > idx + 1 and target_idx <= len(proto.instructions):
            last_then_idx = target_idx - 1
            last_then_insn = proto.instructions[last_then_idx]
            try:
                last_then_op = LuauOpcode(last_then_insn.opcode)
                if last_then_op == LuauOpcode.JUMP:
                    jump_end_pc = get_jump_target(last_then_insn)
                    candidate = self._pc_to_idx(proto, jump_end_pc)
                    if candidate is not None and candidate > target_idx and candidate <= end_idx:
                        has_else = True
                        else_end_idx = candidate
            except ValueError:
                pass

        # Lift the then-body (exclude trailing JUMP if else detected)
        then_end = target_idx - 1 if has_else else target_idx
        then_stmts = self._lift_block(
            proto, idx + 1, then_end,
            registers=dict(registers),
            locals_map=dict(locals_map),
            pending=dict(pending),
            for_call_infos=dict(for_call_infos),
        )

        if has_else:
            # Lift the else-body
            else_stmts = self._lift_block(
                proto, target_idx, else_end_idx,
                registers=dict(registers),
                locals_map=dict(locals_map),
                pending=dict(pending),
                for_call_infos=dict(for_call_infos),
            )

            # Flatten nested if into elseif chain
            if (len(else_stmts) == 1 and isinstance(else_stmts[0], IfStatement)):
                inner_if = else_stmts[0]
                if_stmt = IfStatement(
                    condition=condition,
                    then_body=Body(statements=then_stmts),
                    elseif_clauses=(
                        [(inner_if.condition, inner_if.then_body)]
                        + inner_if.elseif_clauses
                    ),
                    else_body=inner_if.else_body,
                )
            else:
                if_stmt = IfStatement(
                    condition=condition,
                    then_body=Body(statements=then_stmts),
                    else_body=Body(statements=else_stmts),
                )
            resume_idx = else_end_idx
        else:
            if_stmt = IfStatement(
                condition=condition,
                then_body=Body(statements=then_stmts),
            )
            resume_idx = target_idx

        return if_stmt, resume_idx

    def _get_debug_name(self, proto: Proto, reg: int, pc: int) -> Optional[str]:
        """Look up the debug local name for a register at a given PC.

        Skips internal names like '(for index)' that start with '('.
        Returns None if no debug name is available.
        """
        for lv in proto.local_vars:
            if lv.reg == reg and lv.start_pc <= pc <= lv.end_pc:
                if lv.name and not lv.name.startswith("("):
                    return lv.name
        return None

    def _flush_if_pending(
        self,
        reg: int,
        registers: Dict[int, Expression],
        locals_map: Dict[int, Local],
        pending: Dict[int, _PendingExpression],
        stmts: List[Statement],
    ) -> None:
        """Flush a pending expression to a local declaration if needed.

        When a register contains a "pending" expression (like a TableConstructor
        being built up), and another instruction reads from that register,
        we need to emit the expression as a local variable declaration and
        replace the register contents with a LocalRef.

        Args:
            reg: The register number being read.
            registers: Current register state.
            locals_map: Current local variable mappings.
            pending: Pending expression tracker.
            stmts: Statement list to append the declaration to.
        """
        if reg not in pending:
            return

        pend = pending.pop(reg)
        expr = pend.expr

        # Try debug name first, then name hint from pending, then generate
        debug_name = self._get_debug_name(
            self._current_proto, reg, self._current_pc
        ) if self._current_proto else None

        if debug_name:
            name = self.name_gen.use_name(debug_name)
        elif pend.name_hint:
            name = self.name_gen.use_name(pend.name_hint)
        elif isinstance(expr, TableConstructor):
            name = self.name_gen.table_var()
        else:
            name = self.name_gen.next_var()

        local = Local(name=name, reg=reg)
        locals_map[reg] = local
        registers[reg] = LocalRef(local=local)

        stmts.append(LocalDeclaration(
            locals=[local],
            values=[expr],
        ))

    def _get_reg_expr(
        self,
        reg: int,
        registers: Dict[int, Expression],
        locals_map: Dict[int, Local],
    ) -> Expression:
        """Get the expression currently held in a register.

        If the register has a local variable mapped to it, returns a LocalRef.
        Otherwise returns whatever expression is stored, or NilLiteral as fallback.

        Args:
            reg: The register number.
            registers: Current register state.
            locals_map: Current local variable mappings.

        Returns:
            The Expression for the register contents.
        """
        if reg in locals_map:
            # If the register was overwritten with a new (non-local) value
            # since the local was created, use the new value instead of
            # the stale local reference.
            if reg in registers and not isinstance(registers[reg], LocalRef):
                return registers[reg]
            return LocalRef(local=locals_map[reg])
        if reg in registers:
            return registers[reg]
        return NilLiteral()

    def _constant_to_expression(self, proto: Proto, const_idx: int) -> Expression:
        """Convert a constant from the proto's constant pool to an AST Expression.

        Args:
            proto: The proto containing the constant pool.
            const_idx: Index into the constant list.

        Returns:
            An appropriate literal Expression node.
        """
        if const_idx < 0 or const_idx >= len(proto.constants):
            return NilLiteral()

        k = proto.constants[const_idx]

        if k.type == ConstantType.NIL:
            return NilLiteral()
        elif k.type == ConstantType.BOOLEAN:
            return BoolLiteral(value=k.value_bool)
        elif k.type == ConstantType.NUMBER:
            return NumberLiteral(value=k.value_number)
        elif k.type == ConstantType.STRING:
            s = resolve_string(self.chunk, k.value_string_idx)
            return StringLiteral(value=s)
        elif k.type == ConstantType.IMPORT:
            name = resolve_import_name(self.chunk, proto, k.value_import)
            parts = name.split(".")
            if len(parts) == 1:
                return GlobalRef(name=parts[0])
            expr = GlobalRef(name=parts[0])
            for part in parts[1:]:
                expr = DotExpression(table=expr, field_name=part)
            return expr
        else:
            return NilLiteral()

    def _pc_to_idx(self, proto: Proto, target_pc: int) -> Optional[int]:
        """Convert a raw PC (instruction address in the raw bytecode stream) to
        an index into proto.instructions.

        Since AUX words are merged into their parent instructions, the instruction
        list may be shorter than the raw bytecode. We need to find the instruction
        whose .pc field matches the target.

        Args:
            proto: The proto containing the instructions.
            target_pc: The target PC value to find.

        Returns:
            The index into proto.instructions, or None if not found.
        """
        for i, insn in enumerate(proto.instructions):
            if insn.pc == target_pc:
                return i
        # If exact match not found, find the closest instruction at or after target_pc
        for i, insn in enumerate(proto.instructions):
            if insn.pc >= target_pc:
                return i
        return None

    def _lift_closure(self, child_proto: Proto) -> Closure:
        """Lift a child proto into a Closure expression.

        Args:
            child_proto: The proto for the closure's function body.

        Returns:
            A Closure Expression node.
        """
        # Create parameter Locals (use debug names if available)
        params = []
        for i in range(child_proto.num_params):
            debug_name = self._get_debug_name(child_proto, i, 0)
            if debug_name:
                param_name = self.name_gen.use_name(debug_name)
            else:
                param_name = self.name_gen.func_param(i)
            param = Local(name=param_name, reg=i)
            params.append(param)

        # Lift the function body
        body_regs = {}
        body_locals = {}
        for p in params:
            body_locals[p.reg] = p
            body_regs[p.reg] = LocalRef(local=p)

        body_stmts = self._lift_block(
            child_proto, 0, len(child_proto.instructions),
            is_main=False,
            registers=body_regs,
            locals_map=body_locals,
        )

        return Closure(
            params=params,
            is_vararg=child_proto.is_vararg,
            body=Body(statements=body_stmts),
        )
