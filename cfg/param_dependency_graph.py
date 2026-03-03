"""Parameter dependency graph for phi function sequencing.

When destructing SSA form, phi functions in the same block execute
conceptually in parallel. To sequentialize them, we need to analyze
dependencies between phi parameters to avoid lost-copy and swap problems.

Example:
    a = phi(b, ...)
    b = phi(a, ...)
Here, both phis read the OLD values. A naive sequential execution would
produce the wrong result. We need to detect this cycle and break it
with a temporary variable.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from ..block import BasicBlock, PhiFunction


class ParamDependencyGraph:
    """Track dependencies between phi parameters for sequencing.

    Nodes are SSA variable names. An edge from A to B means "A must be
    read before B is written" (B's copy overwrites a value that A needs).

    This graph is used to find a safe execution order for the parallel
    copies derived from phi functions.
    """

    def __init__(self):
        # Adjacency list: node -> set of nodes it depends on (must come before)
        self.deps: Dict[str, Set[str]] = defaultdict(set)
        # All nodes
        self.nodes: Set[str] = set()
        # Copy list: (dest, src) pairs
        self.copies: List[Tuple[str, str]] = []

    def add_copy(self, dest: str, src: str):
        """Register a parallel copy: dest = src.

        This means src must be read before dest is written (if any other
        copy reads dest).
        """
        self.copies.append((dest, src))
        self.nodes.add(dest)
        self.nodes.add(src)

    def build(self):
        """Build the dependency graph from the registered copies.

        For each pair of copies (d1=s1, d2=s2):
        - If s2 == d1 (copy 2 reads what copy 1 writes), then copy 2
          depends on reading s2 before copy 1 writes d1.
        """
        for i, (d1, s1) in enumerate(self.copies):
            for j, (d2, s2) in enumerate(self.copies):
                if i != j and s2 == d1:
                    # Copy j reads d1, which copy i writes
                    # So copy j must read before copy i writes
                    # In terms of execution order: j before i
                    self.deps[d1].add(s2)

    def find_safe_order(self) -> List[Tuple[str, str]]:
        """Find a sequential execution order for the copies.

        Uses topological sort, breaking cycles with temporary variables.

        Returns an ordered list of (dest, src) copies.
        """
        self.build()
        return _topological_sort_with_cycle_breaking(self.copies)

    @classmethod
    def from_phi_functions(
        cls,
        phis: List[PhiFunction],
        pred_block_id: int,
    ) -> 'ParamDependencyGraph':
        """Build a dependency graph from phi functions for a specific predecessor.

        Extracts the parallel copies needed when coming from pred_block_id.
        """
        graph = cls()
        for phi in phis:
            for source_block_id, source_name in phi.sources:
                if source_block_id == pred_block_id:
                    if phi.target != source_name:
                        graph.add_copy(phi.target, source_name)
        return graph


def _topological_sort_with_cycle_breaking(
    copies: List[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """Sort copies topologically, breaking cycles with temporaries.

    A copy (d, s) must execute before any copy that writes s.
    When cycles exist (e.g., a=b, b=a), we break them by introducing
    a temporary variable.
    """
    if not copies:
        return []

    # Remove self-copies
    copies = [(d, s) for d, s in copies if d != s]
    if not copies:
        return []

    # Build: which destinations are read by other copies?
    # If dest D is read as a source by another copy, D can't be written yet
    result = []
    remaining = list(copies)
    temp_counter = [0]

    max_iterations = len(remaining) * 3 + 10

    for _ in range(max_iterations):
        if not remaining:
            break

        # Find a copy whose dest is NOT read by any remaining copy
        found = False
        for i in range(len(remaining)):
            d, s = remaining[i]
            # Check if d is a source in any other remaining copy
            used_as_source = any(s2 == d for d2, s2 in remaining if (d2, s2) != (d, s))
            if not used_as_source:
                result.append(remaining.pop(i))
                found = True
                break

        if not found:
            # Cycle detected. Break it with a temp.
            d, s = remaining[0]
            temp = f"__phi_tmp_{temp_counter[0]}"
            temp_counter[0] += 1

            # Insert: temp = s (save the source)
            result.append((temp, s))

            # Replace this copy's source with the temp
            remaining[0] = (d, temp)

    return result


def sequentialize_phi_copies(
    block: BasicBlock,
    pred_block_id: int,
) -> List[Tuple[str, str]]:
    """Get a safe sequential ordering of phi copies for a predecessor.

    This is a convenience function that combines ParamDependencyGraph
    construction and solving.

    Args:
        block: The block containing phi functions.
        pred_block_id: The predecessor block we're coming from.

    Returns:
        Ordered list of (dest, src) copies to execute sequentially.
    """
    graph = ParamDependencyGraph.from_phi_functions(
        block.phi_functions, pred_block_id
    )
    return graph.find_safe_order()
