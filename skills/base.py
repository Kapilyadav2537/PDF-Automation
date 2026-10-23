"""
skills/base.py
=============================================================================
Core Skill Abstraction & Central Registry System

PURPOSE:
--------
This module defines what a "Skill" is in our PDF modification architecture,
and provides a central `SkillRegistry` to discover, register, and describe
skills to AI models (Google Gemini in `main.py`, Anthropic Claude in
`pdf_agent.py`). It is the single source of truth for both backends.

KEY CONCEPTS:
-------------
1. Skill: A wrapper around any Python function that performs a PDF action
   (e.g., rotate, watermark, split) along with metadata and parameter schemas.
2. SkillRegistry: A catalog where skills register themselves using a Python
   decorator `@registry.register`.
3. Schema Introspection: Uses Python's `inspect` module to automatically turn
   Python function type annotations (and `:param name:` docstring lines) into
   standard JSON schemas that LLMs understand when planning function calls.
4. Path Parameters: Parameters named `input_*_path(s)` are input files and
   `output_*_path(s)` are output files. Executors use this convention to route
   them through the sandbox in `skills/sandbox.py`.
=============================================================================
"""

import inspect
import os
import re
import typing
from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional


class SkillError(ValueError):
    """Raised for bad parameters or failed operations (shown to the user, not a crash)."""


_INPUT_PARAM = re.compile(r"^input_\w*_paths?$")
_OUTPUT_PARAM = re.compile(r"^output_\w*_paths?$")


@dataclass
class Skill:
    """
    Represents an individual executable capability (skill) in the system.

    Fields:
    -------
    name : str
        Unique identifier for the skill (e.g. 'rotate_pages', 'extract_text').
    description : str
        Explanation of what the skill does (read by both humans and the AI model).
    func : Callable
        The underlying Python function that executes the action.
    parameters_schema : Dict[str, Any]
        JSON Schema detailing the accepted arguments, their types, and requirements.
    destructive : bool
        True if the skill writes files (callers ask for confirmation first).
    """
    name: str
    description: str
    func: Callable[..., Any]
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    destructive: bool = True

    @property
    def properties(self) -> Dict[str, Any]:
        return self.parameters_schema.get("properties", {})

    @property
    def required(self) -> List[str]:
        return self.parameters_schema.get("required", [])

    @property
    def input_params(self) -> List[str]:
        return [k for k in self.properties if _INPUT_PARAM.match(k)]

    @property
    def output_params(self) -> List[str]:
        return [k for k in self.properties if _OUTPUT_PARAM.match(k)]

    def execute(self, **kwargs) -> Any:
        """
        Executes the underlying Python function with the provided keyword arguments.
        Example: skill.execute(input_pdf_path='doc.pdf', rotation_angle=90)
        """
        return self.func(**kwargs)

    def validate(self, args: Dict[str, Any]) -> None:
        """Checks `args` against the parameter schema; raises SkillError on problems."""
        unknown = set(args) - set(self.properties)
        if unknown:
            raise SkillError(f"{self.name}: unknown parameter(s) {sorted(unknown)}")
        missing = [r for r in self.required if args.get(r) in (None, "", [])]
        if missing:
            raise SkillError(f"{self.name}: missing required parameter(s) {missing}")
        for k, v in args.items():
            spec = self.properties[k]
            if "enum" in spec and v not in spec["enum"]:
                raise SkillError(f"{self.name}.{k} must be one of {spec['enum']}")
            if spec.get("type") == "integer" and (not isinstance(v, int) or isinstance(v, bool)):
                raise SkillError(f"{self.name}.{k} must be an integer")


class SkillRegistry:
    """
    Central catalog storing all available PDF skills.

    Provides methods to:
    - Register new skills via a decorator `@registry.register(...)`.
    - Retrieve skills by name.
    - List all skills for display in the CLI.
    - Feed skills to LLMs so the model knows what tools it can call.
    """

    def __init__(self):
        # Dictionary mapping skill name -> Skill instance
        self._skills: Dict[str, Skill] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters_schema: Optional[Dict[str, Any]] = None,
        destructive: Optional[bool] = None,
    ):
        """
        Decorator that registers a Python function as a predefined skill.

        Usage Example:
        --------------
        @registry.register(name="rotate_pages", description="Rotates pages by angle")
        def rotate_pages(input_pdf_path: str, rotation_angle: int):
            ...

        :param name: Unique name for the skill.
        :param description: Clear description of what the skill does.
        :param parameters_schema: Optional custom schema; if None, automatically
                                  inferred from function signature.
        :param destructive: Whether the skill writes files. Defaults to True if
                            the skill has any output path parameter.
        """
        def decorator(func: Callable[..., Any]):
            # Auto-generate schema from function signature if not explicitly provided
            schema = parameters_schema or self._generate_simple_schema(func)

            skill = Skill(
                name=name,
                description=description.strip(),
                func=func,
                parameters_schema=schema,
            )
            skill.destructive = bool(skill.output_params) if destructive is None else destructive
            # Store in the internal registry dictionary
            self._skills[name] = skill

            # Return the original function untouched so it can still be called normally
            return func

        return decorator

    def get_skill(self, name: str) -> Optional[Skill]:
        """
        Look up a skill by its registered name.
        Returns the Skill object, or None if not registered.
        """
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        """Returns a list of all currently registered Skill objects."""
        return list(self._skills.values())

    def get_callables(self) -> List[Callable[..., Any]]:
        """
        Returns a list of raw Python functions.
        Useful when binding directly to LLM tool-calling APIs.
        """
        return [skill.func for skill in self._skills.values()]

    def _generate_simple_schema(self, func: Callable[..., Any]) -> Dict[str, Any]:
        """
        Introspects a Python function's arguments and type annotations
        to generate an OpenAPI/JSON-Schema dictionary for AI models.

        How it works:
        -------------
        1. Uses `inspect.signature(func)` to read parameters.
        2. Maps Python types (`str`, `int`, `List[int]`, `Optional[...]`,
           `Literal[...]`, etc.) to JSON schema types.
        3. Uses `:param name: ...` lines from the docstring as descriptions.
        4. Marks parameters without default values as required.
        """
        sig = inspect.signature(func)
        docs = _param_docs(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            prop = _annotation_schema(param.annotation)
            prop["description"] = docs.get(param_name, f"Parameter: {param_name}")
            properties[param_name] = prop

            # If the parameter has no default value, it is required
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }


# Mapping Python types to JSON schema type names
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    os.PathLike: "string",
}


def _annotation_schema(annotation: Any) -> Dict[str, Any]:
    """Converts a type annotation into a JSON-schema fragment (defaults to string)."""
    if annotation in _TYPE_MAP:
        return {"type": _TYPE_MAP[annotation]}

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is typing.Literal:
        return {"type": _TYPE_MAP.get(type(args[0]), "string"), "enum": list(args)}

    if origin is typing.Union:
        options = []
        for arg in args:
            if arg is type(None):
                continue
            schema = _annotation_schema(arg)
            if schema not in options:
                options.append(schema)
        if len(options) == 1:
            return options[0]
        return {"anyOf": options} if options else {"type": "string"}

    if origin in (list, typing.List):
        schema = {"type": "array"}
        if args:
            schema["items"] = _annotation_schema(args[0])
        return schema

    if origin in _TYPE_MAP:
        return {"type": _TYPE_MAP[origin]}

    return {"type": "string"}


def _param_docs(func: Callable[..., Any]) -> Dict[str, str]:
    """Collects `:param name: text` entries (including continuation lines) from a docstring."""
    docs: Dict[str, str] = {}
    current = None
    for line in (inspect.getdoc(func) or "").splitlines():
        match = re.match(r"\s*:param\s+(\w+):\s*(.*)", line)
        if match:
            current = match.group(1)
            docs[current] = match.group(2).strip()
        elif current and line.strip() and not line.lstrip().startswith(":"):
            docs[current] += " " + line.strip()
        else:
            current = None
    return docs


# ---------------------------------------------------------------------------
# Global Registry Instance:
# All modules import this single instance to register or query skills.
# ---------------------------------------------------------------------------
registry = SkillRegistry()
