"""
skills/base.py
=============================================================================
Core Skill Abstraction & Central Registry System

PURPOSE:
--------
This module defines what a "Skill" is in our PDF modification architecture,
and provides a central `SkillRegistry` to discover, register, and describe
skills to AI models like Google Gemini.

KEY CONCEPTS:
-------------
1. Skill: A wrapper around any Python function that performs a PDF action
   (e.g., rotate, watermark, split) along with metadata and parameter schemas.
2. SkillRegistry: A catalog where skills register themselves using a Python
   decorator `@registry.register`.
3. Schema Introspection: Uses Python's `inspect` module to automatically turn
   Python function type annotations into standard JSON schemas that Gemini
   understands when planning function calls.
=============================================================================
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional
import inspect


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
    """
    name: str
    description: str
    func: Callable[..., Any]
    parameters_schema: Dict[str, Any] = field(default_factory=dict)

    def execute(self, **kwargs) -> Any:
        """
        Executes the underlying Python function with the provided keyword arguments.
        Example: skill.execute(input_pdf_path='doc.pdf', rotation_angle=90)
        """
        return self.func(**kwargs)


class SkillRegistry:
    """
    Central catalog storing all available PDF skills.

    Provides methods to:
    - Register new skills via a decorator `@registry.register(...)`.
    - Retrieve skills by name.
    - List all skills for display in the CLI.
    - Feed skills to Gemini so the model knows what tools it can call.
    """

    def __init__(self):
        # Dictionary mapping skill name -> Skill instance
        self._skills: Dict[str, Skill] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters_schema: Optional[Dict[str, Any]] = None
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
        """
        def decorator(func: Callable[..., Any]):
            # Auto-generate schema from function signature if not explicitly provided
            schema = parameters_schema or self._generate_simple_schema(func)
            
            skill = Skill(
                name=name,
                description=description.strip(),
                func=func,
                parameters_schema=schema
            )
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
        2. Maps Python types (`str`, `int`, `list`, etc.) to JSON schema types
           ('string', 'integer', 'array', etc.).
        3. Marks parameters without default values as required.
        """
        sig = inspect.signature(func)
        properties = {}
        required = []

        # Mapping Python types to JSON schema type names
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }

        for param_name, param in sig.parameters.items():
            param_type = "string"
            
            # Check direct type annotations (e.g., rotation_angle: int)
            if param.annotation in type_map:
                param_type = type_map[param.annotation]
            elif hasattr(param.annotation, "__origin__"):
                # Handle generic types like List[int] or Optional[str]
                origin = param.annotation.__origin__
                if origin in type_map:
                    param_type = type_map[origin]

            properties[param_name] = {
                "type": param_type,
                "description": f"Parameter: {param_name}"
            }
            
            # If the parameter has no default value, it is required
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }


# ---------------------------------------------------------------------------
# Global Registry Instance:
# All modules import this single instance to register or query skills.
# ---------------------------------------------------------------------------
registry = SkillRegistry()
