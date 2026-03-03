from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class BasicBlock:
    """A basic block in the control flow graph.

    A basic block is a maximal sequence of instructions with no branches
    except at the entry and exit. Control flow enters at the top and leaves
    at the bottom.
    """
    id: int
    start_pc: int  # first instruction PC
    end_pc: int    # last instruction PC (inclusive)
    instructions: list = field(default_factory=list)  # list of Instruction

    # Control flow edges
    successors: List['BasicBlock'] = field(default_factory=list)
    predecessors: List['BasicBlock'] = field(default_factory=list)

    # Block properties
    is_loop_header: bool = False
    is_loop_latch: bool = False  # back-edge source
    loop_depth: int = 0

    # AST statements generated for this block
    statements: list = field(default_factory=list)

    # SSA-related
    phi_functions: list = field(default_factory=list)  # list of PhiFunction
    dominance_frontier: Set[int] = field(default_factory=set)  # set of block IDs

    # Liveness info (populated by liveness analysis)
    live_in: Set[str] = field(default_factory=set)
    live_out: Set[str] = field(default_factory=set)

    # Definitions and uses for registers in this block
    defs: Set[str] = field(default_factory=set)
    uses: Set[str] = field(default_factory=set)

    def add_successor(self, block: 'BasicBlock'):
        """Add a control flow edge from this block to the given block."""
        if block not in self.successors:
            self.successors.append(block)
        if self not in block.predecessors:
            block.predecessors.append(self)

    def remove_successor(self, block: 'BasicBlock'):
        """Remove a control flow edge from this block to the given block."""
        if block in self.successors:
            self.successors.remove(block)
        if self in block.predecessors:
            block.predecessors.remove(self)

    @property
    def terminator(self):
        """Return the last instruction (the terminator) of this block, or None."""
        if self.instructions:
            return self.instructions[-1]
        return None

    @property
    def is_empty(self) -> bool:
        return len(self.instructions) == 0

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if isinstance(other, BasicBlock):
            return self.id == other.id
        return NotImplemented

    def __repr__(self):
        succ_ids = [b.id for b in self.successors]
        pred_ids = [b.id for b in self.predecessors]
        return (f"Block({self.id}, pc={self.start_pc}-{self.end_pc}, "
                f"succ={succ_ids}, pred={pred_ids})")


@dataclass
class PhiFunction:
    """A phi function placed at a join point in SSA form.

    A phi function merges values from different predecessor blocks.
    Example: x3 = phi(x1 from block0, x2 from block1)
    """
    target: str  # the SSA variable being defined (e.g., "r0_3")
    register: int  # the original register number
    sources: list = field(default_factory=list)  # list of (block_id, ssa_name) tuples

    def __repr__(self):
        src_str = ", ".join(f"{name} from B{bid}" for bid, name in self.sources)
        return f"{self.target} = phi({src_str})"
