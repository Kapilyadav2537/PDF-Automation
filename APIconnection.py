"""
APIconnection.py
=============================================================================
Minimal Standalone Verification Script for Google GenAI Interactions API

PURPOSE:
--------
Quick standalone test to verify that the Google GenAI library is installed
and can communicate with 'gemini-3.8-flash' using your environment's API key.

USAGE:
------
python3 APIconnection.py
=============================================================================
"""

# Import the modern Google GenAI library (v1+)
from google import genai

# Initialize the GenAI client.
# Automatically picks up GEMINI_API_KEY from environment variables if present.
client = genai.Client()

# Send a prompt using the new Interactions API recommended by Google
interaction = client.interactions.create(
    model="gemini-3.8-flash",
    input="Explain how AI works in a few words"
)

# Print the model's text response
print(interaction.output_text)
