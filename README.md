# PDF Modification & Automation Tool

An intelligent PDF modification system with predefined core skills and Google Gemini AI model integration.

---

## 🚀 Step 1: Predefined Skills Set (Testing & Core Tools)

The system includes a modular `SkillRegistry` with 5 foundational PDF modification skills implemented in `skills/pdf_skills.py`:

| Skill Name | Description | Key Parameters |
| :--- | :--- | :--- |
| **`extract_text`** | Extracts plain text from all pages or a subset of pages. | `input_pdf_path`, `pages` (optional list of page numbers) |
| **`rotate_pages`** | Rotates specific or all pages clockwise (90°, 180°, 270°). | `input_pdf_path`, `output_pdf_path`, `rotation_angle`, `pages` |
| **`merge_pdfs`** | Merges multiple PDF files into one output document in order. | `input_pdf_paths` (list), `output_pdf_path` |
| **`split_pdf`** | Extracts specific page ranges (e.g., `'1-3, 5'`) into a new PDF. | `input_pdf_path`, `output_pdf_path`, `page_range` |
| **`add_watermark`**| Stamps a semi-transparent text watermark across PDF pages. | `input_pdf_path`, `output_pdf_path`, `watermark_text`, `pages` |

Each skill is registered using the `@registry.register` decorator, which automatically extracts function signatures and docstrings so the Gemini model can invoke them as tools.

---

## 🔐 Step 2: Loading Gemini Model from a Secret File

Your Gemini API key is kept strictly private and safe from inspection:

1. **Secret File Location**: Stored in a `.env` file in the root directory.
2. **Git Ignored**: `.env` and `*.secret` are listed in `.gitignore` to prevent committing secrets.
3. **Unreadable for AI Assistant**: The assistant will **never** read or inspect your `.env` file directly. Python's `python-dotenv` loads the key directly into memory at runtime.

### Setup Instructions for Secret File:

1. Copy the provided `.env.example` template to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` in your text editor and paste your API key:
   ```env
   GEMINI_API_KEY=AIzaSy...your_actual_key_here
   GEMINI_MODEL_NAME=gemini-3.8-flash
   ```

---

## 📦 Installation & Setup

1. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the interactive tool (select PDF, enter prompt, view skills/parameters & execute):
   ```bash
   python3 main.py
   ```

3. Run automated tests across all predefined skills:
   ```bash
   python3 test_skills.py
   ```

4. Or pass a one-line prompt directly via CLI:
   ```bash
   python3 main.py --prompt "Rotate page 1 of CS201Marks.pdf by 90 degrees and add CONFIDENTIAL watermark"
   ```

---

## 📁 Project Structure

```
PDF-automation/
├── .gitignore               # Protects secret files (.env) from git
├── .env.example             # Template for API credentials
├── requirements.txt         # Dependencies (pypdf, python-dotenv, google-genai, reportlab)
├── README.md                # Project documentation
├── test_skills.py           # Automated test suite for all 5 skills and model loader
├── main.py                  # CLI runner and entry point
├── core/
│   ├── __init__.py
│   ├── config.py            # Safely loads GEMINI_API_KEY from .env
│   └── ai_model.py          # Gemini model loader and agent interface
└── skills/
    ├── __init__.py
    ├── base.py              # Skill registry and metadata schema generator
    └── pdf_skills.py        # 5 predefined PDF modification skills
```

