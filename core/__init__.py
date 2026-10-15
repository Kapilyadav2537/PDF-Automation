"""
core/__init__.py
=============================================================================
Core Module Package Exports

PURPOSE:
--------
Provides convenient imports for configuration and model integration:
- `load_secrets`: Loads credentials from .env.
- `get_gemini_api_key`: Reads the Gemini key safely.
- `get_gemini_model_name`: Retrieves the active model target (e.g. gemini-3.8-flash).
- `mask_secret`: Protects secrets when printing statuses.
- `GeminiPDFModel`: High-level wrapper orchestrating AI reasoning & skill resolution.
=============================================================================
"""

from .config import load_secrets, get_gemini_api_key, get_gemini_model_name, mask_secret
from .ai_model import GeminiPDFModel

__all__ = [
    "load_secrets",
    "get_gemini_api_key",
    "get_gemini_model_name",
    "mask_secret",
    "GeminiPDFModel",
]
