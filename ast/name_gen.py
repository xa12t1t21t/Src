"""Name generator for producing unique variable names during decompilation."""

from typing import Set


class NameGenerator:
    """Generates unique variable names for decompiled code.

    Produces names like v1, v2, v3 for general variables,
    and contextual names like k, v for loop variables,
    i for numeric loop counters, etc.
    """

    # Lua reserved keywords that cannot be used as variable names
    RESERVED = frozenset({
        "and", "break", "do", "else", "elseif", "end",
        "false", "for", "function", "goto", "if", "in",
        "local", "nil", "not", "or", "repeat", "return",
        "then", "true", "until", "while",
        # Luau additions
        "continue", "type", "export",
    })

    def __init__(self):
        self._counter: int = 0
        self._used_names: Set[str] = set()

    def _register(self, name: str) -> str:
        """Register a name as used and return it."""
        self._used_names.add(name)
        return name

    def next_var(self) -> str:
        """Generate the next generic variable name: v1, v2, ..."""
        while True:
            self._counter += 1
            name = f"v{self._counter}"
            if name not in self._used_names and name not in self.RESERVED:
                return self._register(name)

    def next_with_prefix(self, prefix: str) -> str:
        """Generate a name with a given prefix: prefix1, prefix2, ..."""
        n = 0
        while True:
            n += 1
            name = f"{prefix}{n}" if n > 1 else prefix
            if name not in self._used_names and name not in self.RESERVED:
                return self._register(name)

    def for_loop_vars(self, count: int = 2):
        """Generate variable names suitable for generic for loops.

        For pairs(): k, v
        For ipairs(): i, v
        For single var: v
        For 3+ vars: v1, v2, v3, ...
        """
        if count == 1:
            return [self.next_with_prefix("v")]
        elif count == 2:
            return [
                self.next_with_prefix("k"),
                self.next_with_prefix("v"),
            ]
        else:
            return [self.next_var() for _ in range(count)]

    def numeric_for_var(self) -> str:
        """Generate a variable name for a numeric for loop counter."""
        return self.next_with_prefix("i")

    def func_param(self, index: int) -> str:
        """Generate a parameter name for a function.

        First few params get meaningful names: a, b, c, ...
        After that: p1, p2, ...
        """
        simple_names = ["a", "b", "c", "d", "e", "f"]
        if index < len(simple_names):
            name = simple_names[index]
            if name not in self._used_names and name not in self.RESERVED:
                return self._register(name)
        return self.next_with_prefix("p")

    def is_used(self, name: str) -> bool:
        """Check if a name has already been used."""
        return name in self._used_names

    def reserve(self, name: str):
        """Reserve a name so it won't be generated."""
        self._used_names.add(name)

    def reset(self):
        """Reset the generator to its initial state."""
        self._counter = 0
        self._used_names.clear()
