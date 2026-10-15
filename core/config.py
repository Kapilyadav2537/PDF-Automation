"""
core/config.py
=============================================================================
Configuration & Secret File Manager

PURPOSE:
--------
This module handles loading sensitive credentials (like GEMINI_API_KEY)
from a private '.env' file into Python's execution environment.

SECURITY HIGHLIGHTS:
--------------------
1. The '.env' file is listed in .gitignore, preventing accidental Git commits.
2. The AI assistant (Antigravity) NEVER opens or reads the '.env' file directly.
3. Secrets are loaded strictly into memory using python-dotenv.
4. When logging or displaying connection status to the user, secrets are masked
   (e.g., 'AIza...3b8a') so the full key is never exposed on screen.
=============================================================================
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path Configuration:
# Locate the default secret file (.env) relative to this project root:
# __file__ is in 'core/', so parent is 'core/', and parent.parent is the root.
# ---------------------------------------------------------------------------
DEFAULT_SECRET_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_secrets(secret_file_path: Optional[str] = None) -> bool:
    """
    Loads environment secrets from the designated secret file (.env).

    How it works:
    -------------
    - Searches for the specified path or defaults to '<project_root>/.env'.
    - If found, `load_dotenv` reads the key=value pairs into os.environ.
    - If the file does not exist, returns False without raising an error.

    :param secret_file_path: Optional custom path to a secret file.
    :return: True if the file was found and loaded, False otherwise.
    """
    target_path = Path(secret_file_path) if secret_file_path else DEFAULT_SECRET_FILE
    
    if target_path.exists():
        # override=True ensures values in .env replace existing blank environment variables
        load_dotenv(dotenv_path=target_path, override=True)
        return True
    
    return False


def get_gemini_api_key(secret_file_path: Optional[str] = None) -> Optional[str]:
    """
    Retrieves the Gemini API key from the secret file or existing environment.

    Workflow:
    ---------
    1. First attempts to load values from the secret file (.env).
    2. Then reads the variable 'GEMINI_API_KEY' from os.environ.

    :param secret_file_path: Optional custom secret file location.
    :return: The raw API key string if found, otherwise None.
    """
    # 1. Attempt to load from secret file first
    load_secrets(secret_file_path)
    
    # 2. Extract key from os.environ
    return os.getenv("GEMINI_API_KEY")


def get_gemini_model_name() -> str:
    """
    Determines which Gemini AI model to load.

    Logic:
    ------
    - Checks the environment variable 'GEMINI_MODEL_NAME'.
    - Defaults to 'gemini-3.8-flash' (the recommended model).
    - If an older/deprecated model (like 'gemini-2.5-flash') is specified in .env,
      this function automatically upgrades it to 'gemini-3.8-flash' to prevent 404 errors.

    :return: The string identifier of the Gemini model.
    """
    model = os.getenv("GEMINI_MODEL_NAME")
    
    # Automatically upgrade deprecated 2.5 flash to 3.8 flash
    if not model or model in ("gemini-2.5-flash", "models/gemini-2.5-flash"):
        return "gemini-3.8-flash"
    
    return model


def mask_secret(secret: Optional[str]) -> str:
    """
    Safely masks a secret string so it can be printed in logs without leaking.

    Example:
    --------
    - Input : "AIzaSyDk83jfkd92kfls93jfksl"
    - Output: "AIza...fksl"

    :param secret: The plain secret key string.
    :return: Masked representation string for safe status output.
    """
    if not secret:
        return "[Not Found]"
    
    # If the key is very short, mask completely
    if len(secret) <= 8:
        return "****"
    
    # Show only the first 4 and last 4 characters
    return f"{secret[:4]}...{secret[-4:]}"
