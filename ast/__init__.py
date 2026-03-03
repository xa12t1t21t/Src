"""AST node types for the Luau bytecode decompiler.

This package contains all AST node types representing Lua language
constructs, plus utilities for traversal, formatting, and transformation.
"""

# Base types
from .lib import ASTNode, Expression, Statement, Body

# Literals
from .literal import NumberLiteral, StringLiteral, BoolLiteral, NilLiteral

# Variables
from .local import Local, LocalRef
from .global_ref import GlobalRef

# Table
from .table import TableField, TableConstructor

# Calls
from .call import FunctionCall, MethodCall, FunctionCallStatement

# Loops
from .for_ import GenericFor, NumericFor
from .while_ import WhileLoop
from .repeat import RepeatUntil

# Assignments and declarations
from .assign import Assignment
from .local_declarations import LocalDeclaration

# Return
from .return_ import Return

# Operators
from .binary import BinaryOp
from .unary import UnaryOp

# Indexing
from .index import IndexExpression, DotExpression

# Closures
from .closure import Closure

# Control flow
from .if_ import IfStatement
from .break_ import Break
from .continue_ import Continue
from .goto import Goto, Label

# Vararg
from .vararg import VarargExpression

# Internal bytecode ops
from .close import CloseUpvalues
from .set_list import SetList

# Formatter
from .formatter import format_body, format_statement, format_expression

# Traversal
from .traverse import walk, walk_statements, walk_expressions

# Name generation and local naming
from .name_gen import NameGenerator
from .name_locals import name_locals

# Local replacement
from .replace_locals import replace_local

# Side effect analysis
from .side_effects import has_side_effects

# Type system
from .type_system import (
    LuaType, NilType, BooleanType, NumberType, StringType,
    TableType, FunctionType, AnyType, UnionType, infer_type,
)

__all__ = [
    # Base
    "ASTNode", "Expression", "Statement", "Body",
    # Literals
    "NumberLiteral", "StringLiteral", "BoolLiteral", "NilLiteral",
    # Variables
    "Local", "LocalRef", "GlobalRef",
    # Table
    "TableField", "TableConstructor",
    # Calls
    "FunctionCall", "MethodCall", "FunctionCallStatement",
    # Loops
    "GenericFor", "NumericFor", "WhileLoop", "RepeatUntil",
    # Assignments
    "Assignment", "LocalDeclaration",
    # Return
    "Return",
    # Operators
    "BinaryOp", "UnaryOp",
    # Indexing
    "IndexExpression", "DotExpression",
    # Closures
    "Closure",
    # Control flow
    "IfStatement", "Break", "Continue", "Goto", "Label",
    # Vararg
    "VarargExpression",
    # Internal
    "CloseUpvalues", "SetList",
    # Formatter
    "format_body", "format_statement", "format_expression",
    # Traversal
    "walk", "walk_statements", "walk_expressions",
    # Naming
    "NameGenerator", "name_locals",
    # Replacement
    "replace_local",
    # Analysis
    "has_side_effects",
    # Types
    "LuaType", "NilType", "BooleanType", "NumberType", "StringType",
    "TableType", "FunctionType", "AnyType", "UnionType", "infer_type",
]
