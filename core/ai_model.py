"""
core/ai_model.py
=============================================================================
Gemini AI Model Loader & PDF Automation Orchestrator

PURPOSE:
--------
This module acts as the "brain" connecting Google's Gemini LLM to the PDF
modification tool. It:
1. Securely initializes the Gemini API client using the API key loaded from .env.
2. Uses the Google GenAI SDK (`google-genai`), via the Interactions API when
   available and `models.generate_content` otherwise.
3. Sends natural language user prompts and available PDF modification skills
   to Gemini so the AI can decide which skills and parameters to execute.
4. Tells the user if no skill exists to fulfill their prompt (e.g., audio/OCR).
=============================================================================
"""

import os
from typing import Optional, List, Dict, Any, Callable
from .config import get_gemini_api_key, get_gemini_model_name, mask_secret


class GeminiPDFModel:
    """
    High-level wrapper around the Google Gemini API.

    Attributes:
    -----------
    api_key : str or None
        The Gemini API key loaded from the secret file (.env).
    model_name : str
        The model identifier (defaults to 'gemini-3.8-flash').
    client : object
        The active Google GenAI SDK client instance.
    sdk_type : str
        Human-readable label indicating which SDK was detected ('google-genai (v1+)').
    """

    def __init__(
        self,
        secret_file_path: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        """
        Initializes the model wrapper:
        1. Reads the API key using core/config.py (keeps key private).
        2. Detects the model name (defaults to 'gemini-3.8-flash').
        3. Instantiates the Google client.
        """
        # Load API key strictly through config loader (Antigravity never reads .env directly)
        self.api_key = get_gemini_api_key(secret_file_path)
        
        # Determine model target (e.g. gemini-3.8-flash)
        self.model_name = model_name or get_gemini_model_name()
        
        # Client handle and detected SDK type
        self.client = None
        self.sdk_type = None
        
        # Connect to SDK
        self._init_client()

    def is_configured(self) -> bool:
        """
        Checks whether a valid API key has been supplied.
        Returns True if the key is present and not the placeholder string.
        """
        return bool(self.api_key and self.api_key != "your_actual_gemini_api_key_here")

    def get_status_info(self) -> Dict[str, Any]:
        """
        Returns a dictionary of status details safe to print to the console.
        The API key is masked (e.g., 'AIza...4f12') to protect secrets.
        """
        return {
            "configured": self.is_configured(),
            "api_key_masked": mask_secret(self.api_key),
            "model_name": self.model_name,
            "sdk_detected": self.sdk_type or "None (Please run: pip install google-genai)"
        }

    def _init_client(self):
        """
        Internal helper: Instantiates the official Google GenAI client
        (`from google import genai`, the `google-genai` package).
        """
        if not self.is_configured():
            return

        try:
            from google import genai
            # client initialized with explicit API key
            self.client = genai.Client(api_key=self.api_key)
            self.sdk_type = "google-genai (v1+)"
        except ImportError:
            self.sdk_type = None

    def _generate_response(self, prompt: str) -> str:
        """
        Internal helper: Dispatches a prompt to Gemini and extracts the text reply.

        Handles:
        1. Modern Interactions API: `client.interactions.create()` (Recommended for 3.8 flash)
        2. Modern Models API: `client.models.generate_content()`
        """
        if self.sdk_type == "google-genai (v1+)":
            # 1. Try modern Interactions API if supported by the installed library
            if hasattr(self.client, "interactions"):
                try:
                    interaction = self.client.interactions.create(
                        model=self.model_name,
                        input=prompt
                    )
                    # Extract output text attribute
                    text = getattr(interaction, "output_text", None) or getattr(interaction, "text", None)
                    if text:
                        return text.strip()
                except Exception:
                    # If interactions API raises an issue, fall back to models.generate_content
                    pass

            # 2. Try models.generate_content
            if hasattr(self.client, "models"):
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return response.text.strip()

            raise RuntimeError("google-genai client does not have interactions or models endpoints.")

        else:
            raise RuntimeError("Gemini SDK not installed. Please run: pip install google-genai")

    def verify_connection(self) -> Dict[str, Any]:
        """
        Sends a simple verification ping to Gemini to test that:
        1. The API key is valid.
        2. The selected model exists and responds.
        3. Network connectivity is operational.

        :return: Dict containing {"success": True/False, "response": ..., "error": ...}
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Gemini API key is not configured. Please add your GEMINI_API_KEY into the secret '.env' file."
            }

        try:
            # Send a minimal, fast test prompt
            reply = self._generate_response("Reply with: 'Gemini PDF modification agent is online.'")
            return {
                "success": True,
                "model": self.model_name,
                "sdk": self.sdk_type,
                "response": reply
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def generate_plan_with_skills(
        self,
        user_request: str,
        available_skills_info: str
    ) -> str:
        """
        Simple text-based planning helper that asks Gemini to analyze a user prompt
        against a plain-text description of available skills.
        """
        if not self.is_configured():
            raise RuntimeError("Gemini model is not configured with an API key.")

        system_instruction = (
            "You are an expert PDF Automation Assistant. "
            "You have access to a set of predefined PDF modification skills:\n"
            f"{available_skills_info}\n\n"
            "Given the user's request, specify the exact steps and skill calls (function name & parameters) "
            "needed to accomplish the task."
        )

        full_prompt = f"{system_instruction}\n\nUser Request: {user_request}"
        return self._generate_response(full_prompt)

    def plan_skills_for_prompt(
        self,
        user_prompt: str,
        selected_pdfs: List[Dict[str, Any]],
        available_skills: List[Any],
        output_dir: str = "output"
    ) -> Dict[str, Any]:
        """
        Core Intelligent Orchestrator:
        -----------------------------
        1. Formats the available skills and user's selected PDFs into structured data.
        2. Instructs Gemini to evaluate if any available skill can accomplish the request.
        3. If NO skill is available (e.g. user asks to compress, convert to MP3 audio, translate),
           Gemini marks `"can_accomplish": false` and explains what capability is missing.
        4. If skills CAN accomplish it, Gemini returns exact steps with parameter values
           (e.g., input path, output path, rotation angles, watermark text, page numbers).
        5. Parses Gemini's JSON reply cleanly into a Python dictionary.

        :param user_prompt: Natural language request from user (e.g. "rotate page 1 by 90 deg")
        :param selected_pdfs: List of metadata dicts for target PDFs chosen by user
        :param available_skills: List of registered Skill objects
        :param output_dir: Directory where resulting PDFs should be saved
        :return: Structured dictionary with plan details
        """
        import json
        import re

        if not self.is_configured():
            raise RuntimeError("Gemini model is not configured with an API key. Check '.env'.")

        # -------------------------------------------------------------------
        # Step 1: Serialize skills and schemas into JSON format for the model
        # -------------------------------------------------------------------
        skills_summary = []
        for s in available_skills:
            skills_summary.append({
                "name": s.name,
                "description": s.description,
                "parameters_schema": s.parameters_schema
            })

        # -------------------------------------------------------------------
        # Step 2: Serialize selected PDF metadata for the model
        # -------------------------------------------------------------------
        pdfs_summary = []
        for p in selected_pdfs:
            pdfs_summary.append({
                "filename": p.get("filename", ""),
                "path": str(p.get("path", "")),
                "total_pages": p.get("total_pages", "Unknown")
            })

        # -------------------------------------------------------------------
        # Step 3: Construct the prompt commanding Gemini to output strict JSON
        # -------------------------------------------------------------------
        prompt = f"""You are an expert AI orchestrator for a PDF modification tool.

PREDEFINED AVAILABLE SKILLS:
{json.dumps(skills_summary, indent=2)}

TARGET PDF FILES SELECTED BY USER:
{json.dumps(pdfs_summary, indent=2)}

USER REQUEST:
"{user_prompt}"

TASK:
1. Determine whether the user's request can be accomplished using ONLY the PREDEFINED AVAILABLE SKILLS listed above.
2. If NO skill is capable of performing the request (for example, if the user asks to compress PDF, convert to audio/word/excel, perform OCR on images, translate languages, edit font colors, etc., and no such skill exists):
   Set "can_accomplish": false. Provide a clear and helpful explanation of why it cannot be accomplished and specify what capability is missing.
3. If one or more skills CAN accomplish the request:
   Set "can_accomplish": true.
   In "steps", provide the ordered list of skills to execute with exact, valid parameters matching their schema.
   For output files, use the folder "{output_dir}" with clean, descriptive filenames.
   If chaining multiple skills, the output of step N should be the input of step N+1.

OUTPUT FORMAT:
Respond with ONLY valid JSON (no markdown formatting, no commentary outside JSON) in this exact schema:
{{
  "can_accomplish": true or false,
  "reason": "Detailed explanation of whether and how the request can or cannot be accomplished with available skills",
  "missing_capability": null or "string describing missing capability if false",
  "steps": [
    {{
      "step_number": 1,
      "skill": "exact_registered_skill_name",
      "explanation": "Brief explanation of this step",
      "parameters": {{
        "parameter_name": "parameter_value"
      }}
    }}
  ]
}}"""

        # -------------------------------------------------------------------
        # Step 4: Dispatch to Gemini
        # -------------------------------------------------------------------
        response_text = self._generate_response(prompt)

        # -------------------------------------------------------------------
        # Step 5: Clean markdown code blocks (e.g. ```json ... ```) if returned
        # -------------------------------------------------------------------
        clean_text = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.MULTILINE)
        clean_text = re.sub(r"```\s*$", "", clean_text.strip(), flags=re.MULTILINE).strip()

        # -------------------------------------------------------------------
        # Step 6: Parse the JSON response
        # -------------------------------------------------------------------
        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            # Fallback: Extract JSON object using regex if LLM added preamble text
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass

            # Safe fallback if completely unparseable
            return {
                "can_accomplish": True,
                "reason": response_text,
                "raw_response": response_text,
                "steps": []
            }
