"""
main.py
=============================================================================
Main Application Entry Point & Interactive CLI Assistant

PURPOSE:
--------
This script provides the interactive user-facing command-line interface.
It ties together:
1. File Discovery: Scans both source ('testpdfs/') and generated ('output/') PDFs.
2. User Selection: Allows selecting one or more PDFs, or typing a custom path.
3. Natural Language Prompting: Takes instructions like "Rotate page 1 by 90 deg".
4. AI Orchestration: Asks Gemini to resolve which predefined skills and parameters
   to run, or clearly warn the user if no skill exists for their request.
5. Execution Engine: Sequentially runs the planned skills and chains outputs.
=============================================================================
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from pypdf import PdfReader

# Import skill registry and AI model loader
from skills import registry, Ctx, SkillError, mask_secrets
from core import GeminiPDFModel

# ---------------------------------------------------------------------------
# Project Directories
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
TESTPDFS_DIR = PROJECT_ROOT / "testpdfs"   # Directory for user's input/source PDFs
OUTPUT_DIR = PROJECT_ROOT / "output"       # Directory for resultant/modified PDFs


def make_sandbox() -> Ctx:
    """Inputs must live in 'testpdfs/' (or 'output/' for chaining); outputs are confined to 'output/'."""
    return Ctx(TESTPDFS_DIR, OUTPUT_DIR, overwrite=True)


def display_banner():
    """Prints a styled ASCII welcome banner."""
    print("""
╔════════════════════════════════════════════════════════════════════╗
║                   PDF MODIFICATION AI ASSISTANT                   ║
║         Interactive Skill Selection & Parameter Resolution         ║
╚════════════════════════════════════════════════════════════════════╝
""")


def get_available_pdfs() -> List[Dict[str, Any]]:
    """
    Scans the filesystem for PDFs available to operate on.

    Sources scanned:
    ----------------
    1. 'testpdfs/': Original documents uploaded/placed by the user.
    2. 'output/': Resultant documents produced by previous modifications.
                  Enables chaining multiple operations (e.g., rotate then watermark).

    :return: List of dictionaries with metadata (filename, path, pages, size, source).
    """
    found_pdfs = []

    # 1. Source PDFs from testpdfs/
    if TESTPDFS_DIR.exists():
        for pdf_path in sorted(TESTPDFS_DIR.glob("*.pdf")):
            try:
                reader = PdfReader(str(pdf_path))
                total_pages = len(reader.pages)
            except Exception:
                total_pages = "Unknown"

            found_pdfs.append({
                "filename": pdf_path.name,
                "path": str(pdf_path.resolve()),
                "source": "input",
                "folder": "testpdfs",
                "total_pages": total_pages,
                "mtime": pdf_path.stat().st_mtime,
                "size_kb": f"{pdf_path.stat().st_size / 1024:.1f} KB"
            })

    # 2. Resultant PDFs from output/ (sorted newest first by modification time)
    if OUTPUT_DIR.exists():
        for pdf_path in sorted(OUTPUT_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                reader = PdfReader(str(pdf_path))
                total_pages = len(reader.pages)
            except Exception:
                total_pages = "Unknown"

            found_pdfs.append({
                "filename": pdf_path.name,
                "path": str(pdf_path.resolve()),
                "source": "resultant",
                "folder": "output",
                "total_pages": total_pages,
                "mtime": pdf_path.stat().st_mtime,
                "size_kb": f"{pdf_path.stat().st_size / 1024:.1f} KB"
            })

    return found_pdfs


def select_target_pdfs(last_generated: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Interactive prompt asking the user to choose which PDF(s) to process.

    Supported Input Formats:
    ------------------------
    - Single index: '1'
    - Multiple comma-separated indices: '1, 2'
    - All available files: 'all'
    - Latest resultant shortcut: 'L'
    - Custom file path: 'C' (prompts for manual path)

    :param last_generated: Filepath of the most recently produced PDF (if any).
    :return: List of chosen PDF metadata dictionaries.
    """
    available = get_available_pdfs()

    print("\n[Step 1] Select PDF(s) to operate on:")
    print("=" * 72)

    input_pdfs = [p for p in available if p.get("source") == "input"]
    resultant_pdfs = [p for p in available if p.get("source") == "resultant"]

    # 1. Display input source PDFs
    if input_pdfs:
        print("  📁 Source PDFs ('testpdfs/'):")
        for idx, pdf in enumerate(input_pdfs, 1):
            print(f"    [{idx}] {pdf['filename']:<40} ({pdf['total_pages']} pages, {pdf['size_kb']})")
    else:
        print("  (No PDFs found in 'testpdfs/' folder.)")

    # 2. Display resultant / output PDFs
    offset = len(input_pdfs)
    if resultant_pdfs:
        print("\n  📄 Resultant / Output PDFs ('output/'):")
        for idx, pdf in enumerate(resultant_pdfs, offset + 1):
            is_latest = last_generated and (str(Path(pdf["path"]).resolve()) == str(Path(last_generated).resolve()))
            badge = " [LATEST RESULTANT ⭐]" if is_latest else ""
            print(f"    [{idx}] {pdf['filename']:<40} ({pdf['total_pages']} pages, {pdf['size_kb']}){badge}")

    # Display selection options
    print("\n  Options:")
    if last_generated and os.path.exists(last_generated):
        print(f"    [L] Select latest resultant PDF: {Path(last_generated).name}")
    elif resultant_pdfs:
        print(f"    [L] Select latest resultant PDF: {resultant_pdfs[0]['filename']}")
    print("    [C] Enter custom PDF file path manually")
    print("=" * 72)

    # Input validation loop
    while True:
        prompt_hint = "e.g. '1', '1, 2', 'all', 'L' for latest resultant, or 'C'"
        choice = input(f"\nEnter your selection ({prompt_hint}): ").strip()

        # Default behavior on empty Enter key
        if not choice:
            if last_generated and os.path.exists(last_generated):
                match = next((p for p in available if p["path"] == str(Path(last_generated).resolve())), None)
                if match:
                    return [match]
            if available:
                return [available[0]]
            continue

        # Handle 'L' / 'l' for Latest Resultant
        if choice.lower() == "l":
            if last_generated and os.path.exists(last_generated):
                match = next((p for p in available if p["path"] == str(Path(last_generated).resolve())), None)
                if match:
                    return [match]
                return [{
                    "filename": Path(last_generated).name,
                    "path": str(Path(last_generated).resolve()),
                    "total_pages": len(PdfReader(last_generated).pages)
                }]
            elif resultant_pdfs:
                return [resultant_pdfs[0]]
            else:
                print("❌ No resultant PDFs generated yet.")
                continue

        # Handle 'C' / 'c' for Custom manual path
        if choice.lower() == "c":
            custom_path = input("Enter path to custom PDF file: ").strip().strip("'\"")
            if not os.path.exists(custom_path):
                print(f"❌ File does not exist: '{custom_path}'. Try again.")
                continue
            try:
                make_sandbox().src(Path(custom_path).resolve())
            except SkillError:
                print(f"❌ '{custom_path}' is outside 'testpdfs/' and 'output/'. Copy it into 'testpdfs/' first.")
                continue
            try:
                reader = PdfReader(custom_path)
                pages = len(reader.pages)
            except Exception:
                pages = "Unknown"
            return [{
                "filename": Path(custom_path).name,
                "path": str(Path(custom_path).resolve()),
                "total_pages": pages
            }]

        # Handle 'all' selection
        if choice.lower() == "all":
            if not available:
                print("❌ No PDFs available.")
                continue
            return available

        # Handle comma-separated indices (e.g. '1, 2')
        try:
            indices = [int(x.strip()) for x in choice.split(",") if x.strip()]
            selected = []
            for i in indices:
                if 1 <= i <= len(available):
                    selected.append(available[i - 1])
                else:
                    print(f"⚠️ Index {i} is out of range (1 to {len(available)}).")
            if selected:
                return selected
            print("❌ No valid PDFs selected. Try again.")
        except ValueError:
            print("❌ Invalid input. Please enter numbers like '1', '4', 'L', 'all', or 'C'.")


def show_plan_and_parameters(plan_result: Dict[str, Any]) -> bool:
    """
    Renders Gemini's analysis:
    - If no skill is available: Prints an alert box detailing why the prompt cannot
      be satisfied and which capability is missing.
    - If skills are matched: Displays the planned steps, skill names, and exact
      parameter values resolved by Gemini.

    :param plan_result: Parsed dictionary from GeminiPDFModel.plan_skills_for_prompt()
    :return: True if executable steps were found, False otherwise.
    """
    can_accomplish = plan_result.get("can_accomplish", False)
    reason = plan_result.get("reason", "")
    steps = plan_result.get("steps", [])

    # Case 1: No skill can accomplish the request
    if not can_accomplish or not steps:
        print("\n" + "═" * 72)
        print("❌ NO PREDEFINED SKILL AVAILABLE TO ACCOMPLISH THIS PROMPT")
        print("═" * 72)
        print(f"\nReason / Analysis:\n{reason}")
        if plan_result.get("missing_capability"):
            print(f"\nMissing Capability : {plan_result.get('missing_capability')}")

        print("\nCurrently Available Predefined Skills:")
        for s in registry.list_skills():
            print(f"  • {s.name:<16} : {s.description}")
        print("═" * 72)
        return False

    # Case 2: Matching skills identified
    print("\n" + "═" * 72)
    print("✔ MATCHING SKILL(S) & SET PARAMETERS RESOLVED")
    print("═" * 72)
    if reason:
        print(f"Plan Summary: {reason}\n")

    for idx, step in enumerate(steps, 1):
        skill_name = step.get("skill", "unknown")
        explanation = step.get("explanation", "")
        params = step.get("parameters", {})

        print(f"Step {idx}: Skill -> [{skill_name}]")
        if explanation:
            print(f"  • Action: {explanation}")
        print("  • Set Parameters:")
        for k, v in mask_secrets(params).items():
            print(f"      {k:<18} = {repr(v)}")
        print("-" * 72)
    print("═" * 72)
    return True


def execute_plan(steps: List[Dict[str, Any]]) -> Optional[str]:
    """
    Executes the resolved steps sequentially using the registered Python skills.

    Process:
    --------
    1. Looks up each skill by name in `registry` and validates its parameters.
    2. Runs it inside the sandbox: inputs must live in 'testpdfs/' (or 'output/'),
       outputs are confined to 'output/'.
    3. Tracks the final PDF produced.
    4. Optionally offers to copy the resulting PDF to 'testpdfs/' for future operations.

    :param steps: Ordered list of step dictionaries from Gemini's plan.
    :return: Path string to the final resultant PDF, or None if failed.
    """
    ctx = make_sandbox()
    print("\n[Executing Planned Skills]...")
    last_output = None

    for idx, step in enumerate(steps, 1):
        skill_name = step.get("skill")
        params = step.get("parameters", {})
        skill = registry.get_skill(skill_name)

        if not skill:
            print(f"❌ Error: Skill '{skill_name}' is not registered in the system.")
            return None

        print(f"\n▶ Executing Step {idx}: {skill_name}...")
        try:
            skill.validate(params)
            result, written = ctx.run(skill, params)
            print(f"  ✔ {result}")
            pdfs = [p for p in written if p.suffix.lower() == ".pdf"]
            if pdfs:
                last_output = str(pdfs[-1])
        except Exception as e:
            print(f"  ❌ Execution failed in Step {idx}: {e}")
            return None

    if last_output and os.path.exists(last_output):
        print(f"\n🎉 Finished! Resultant PDF ready at:\n   {last_output}")

        # Optional convenience: allow copying the resultant file into testpdfs/
        copy_choice = input("\nCopy this resultant PDF into 'testpdfs/' for future use? (y/n) [default: n]: ").strip().lower()
        if copy_choice in ("y", "yes"):
            TESTPDFS_DIR.mkdir(parents=True, exist_ok=True)
            dest = TESTPDFS_DIR / Path(last_output).name
            shutil.copy2(last_output, dest)
            print(f"  ✔ Copied to: {dest}")

        return last_output
    return None


def interactive_session():
    """
    Main interactive loop:
    1. Displays system banner and verifies model status.
    2. In a loop:
       - Prompts user to select PDF(s).
       - Prompts user to enter their modification instruction.
       - Dispatches request to Gemini to determine skills and parameters.
       - Displays formatted plan or missing skill alert.
       - Optionally executes the plan if user confirms.
       - Asks if user wants to operate on another PDF or exit.
    """
    display_banner()
    model = GeminiPDFModel()
    status = model.get_status_info()

    print("System Status:")
    print(f" • Gemini Model Target : {status['model_name']}")
    print(f" • API Key Configured  : {'✔ YES' if status['configured'] else '❌ NO (Check .env)'}")
    print(f" • SDK Detected        : {status['sdk_detected']}")

    if not model.is_configured():
        print("\n❌ Gemini API key is missing. Please add GEMINI_API_KEY into your secret '.env' file.")
        sys.exit(1)

    # Tracks the most recently generated PDF across loop iterations
    last_generated_pdf: Optional[str] = None

    while True:
        # Step 1: Select target PDFs (includes input and resultant PDFs)
        selected_pdfs = select_target_pdfs(last_generated=last_generated_pdf)
        print(f"\n✔ Selected {len(selected_pdfs)} PDF(s):")
        for p in selected_pdfs:
            print(f"   • {p['filename']} ({p.get('total_pages', '?')} pages) [{p.get('folder', 'custom')}]")

        # Step 2: Input prompt
        print("\n[Step 2] Enter your modification prompt:")
        user_prompt = input("Prompt > ").strip()
        if not user_prompt:
            print("Prompt cannot be empty.")
            continue

        # Step 3: Analyze with Gemini
        print(f"\n[Step 3] Asking Gemini ({model.model_name}) to resolve skills and parameters...")
        available_skills = registry.list_skills()
        plan_result = model.plan_skills_for_prompt(
            user_prompt=user_prompt,
            selected_pdfs=selected_pdfs,
            available_skills=available_skills,
            output_dir=str(OUTPUT_DIR)
        )

        # Step 4: Show skills and set parameters
        can_execute = show_plan_and_parameters(plan_result)

        # Step 5: Optional execution
        if can_execute and plan_result.get("steps"):
            confirm = input("\nWould you like to execute this plan now? (y/n) [default: y]: ").strip().lower()
            if confirm in ("", "y", "yes"):
                res_pdf = execute_plan(plan_result["steps"])
                if res_pdf:
                    last_generated_pdf = res_pdf

        # Loop control: Ask whether to run another operation
        again = input("\nOperate on another PDF or prompt? (y/n) [default: n]: ").strip().lower()
        if again not in ("y", "yes"):
            print("\nExiting PDF Modification Tool. Goodbye!\n")
            break


def main():
    """
    Parses CLI flags or launches the interactive session.
    Flags:
      --test    : Runs the automated test suite in test_skills.py.
      --prompt  : Processes a single prompt non-interactively and prints the plan.
    """
    parser = argparse.ArgumentParser(description="PDF Modification Tool with AI Agent")
    parser.add_argument("--test", action="store_true", help="Run automated test suite on predefined skills")
    parser.add_argument("--prompt", type=str, help="Run non-interactively with a single prompt")
    args = parser.parse_args()

    if args.test:
        from test_skills import test_predefined_skills, test_gemini_model_loader
        test_predefined_skills()
        test_gemini_model_loader()
    elif args.prompt:
        model = GeminiPDFModel()
        available_skills = registry.list_skills()
        pdfs = get_available_pdfs()
        plan = model.plan_skills_for_prompt(args.prompt, pdfs, available_skills)
        show_plan_and_parameters(plan)
    else:
        # Default mode: interactive session
        interactive_session()


if __name__ == "__main__":
    main()
