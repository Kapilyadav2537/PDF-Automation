"""
test_skills.py
=============================================================================
Self-Contained Automated Verification Suite

PURPOSE:
--------
This script runs a complete health check on:
1. All predefined PDF modification skills (extract, rotate, merge, split, watermark).
2. The Gemini AI model connection (verifies private .env loading and API ping).

HOW IT RUNS:
------------
- Scans the 'testpdfs/' folder to find the user's real sample PDFs.
- If no files are present in 'testpdfs/', automatically generates fallback sample PDFs.
- Exercises each skill function against the test PDFs and asserts that the
  output PDF files are created and match expected properties (e.g. rotation, page count).
- Sends a quick ping prompt to Gemini to confirm API connectivity.
=============================================================================
"""

import os
import sys
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pypdf import PdfReader

# Import skills from local package
from skills import (
    registry,
    extract_text,
    rotate_pages,
    merge_pdfs,
    split_pdf,
    add_watermark,
)

# Import AI model wrapper from core package
from core import GeminiPDFModel

# ---------------------------------------------------------------------------
# Directory Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
TEST_DIR = PROJECT_ROOT / "test_output"
TESTPDFS_DIR = PROJECT_ROOT / "testpdfs"
RESULTS_DIR = TEST_DIR / "results"


def get_available_test_pdfs():
    """
    Scans the 'testpdfs/' directory and returns a sorted list of Path objects
    for all '.pdf' files present.
    """
    if TESTPDFS_DIR.exists() and TESTPDFS_DIR.is_dir():
        pdfs = sorted(list(TESTPDFS_DIR.glob("*.pdf")))
        return pdfs
    return []


def create_sample_pdf(filepath: Path, title: str, num_pages: int = 2):
    """
    Fallback helper: Generates a small multi-page test PDF using ReportLab
    if no files exist in the 'testpdfs/' folder.

    :param filepath: Target path for the sample PDF.
    :param title: Header text for each page.
    :param num_pages: Number of pages to generate.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(filepath), pagesize=letter)
    for i in range(1, num_pages + 1):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(100, 700, f"{title}")
        c.setFont("Helvetica", 12)
        c.drawString(100, 670, f"Page number: {i}")
        c.drawString(100, 640, f"Sample text content for page {i} of {title}.")
        c.showPage()  # Commit page and advance to next
    c.save()


def test_predefined_skills():
    """
    Executes tests across the predefined PDF skills:
    1. Text extraction
    2. Clockwise page rotation
    3. Multi-file merging
    4. Page range splitting
    5. Semi-transparent text watermarking
    """
    print("=" * 65)
    print("STEP 1: TESTING PREDEFINED PDF SKILLS")
    print("=" * 65)

    test_pdfs = get_available_test_pdfs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if test_pdfs:
        print(f"✔ Found {len(test_pdfs)} PDF(s) in 'testpdfs/' directory:")
        for idx, pdf in enumerate(test_pdfs, 1):
            reader = PdfReader(str(pdf))
            print(f"   [{idx}] {pdf.name} ({len(reader.pages)} pages, {pdf.stat().st_size / 1024:.1f} KB)")
        
        # Select first two PDFs for tests
        doc_a = test_pdfs[0]
        doc_b = test_pdfs[1] if len(test_pdfs) > 1 else test_pdfs[0]
    else:
        print("ℹ No PDFs found in 'testpdfs/'. Generating fallback sample PDFs...")
        doc_a = TEST_DIR / "sample_inputs" / "sample_a.pdf"
        doc_b = TEST_DIR / "sample_inputs" / "sample_b.pdf"
        create_sample_pdf(doc_a, "Document Alpha", num_pages=3)
        create_sample_pdf(doc_b, "Document Beta", num_pages=2)
        print(f"✔ Created fallback test PDFs: {doc_a.name} & {doc_b.name}")

    # -----------------------------------------------------------------------
    # Skill 1: Extract Text
    # -----------------------------------------------------------------------
    print(f"\n--- Skill 1: Extract Text (Target: {doc_a.name}) ---")
    extracted = extract_text(doc_a, pages=[1])
    first_lines = extracted.splitlines()[:5]
    print("Preview of extracted text:")
    for line in first_lines:
        print(f"  > {line}")
    assert len(extracted.strip()) > 0, "Failed: Extracted text is empty"
    print("✔ extract_text passed")

    # -----------------------------------------------------------------------
    # Skill 2: Rotate Pages
    # -----------------------------------------------------------------------
    print(f"\n--- Skill 2: Rotate Pages (Target: {doc_a.name}) ---")
    rotated_out = RESULTS_DIR / f"{doc_a.stem}_rotated_90deg.pdf"
    res_rot = rotate_pages(doc_a, rotated_out, rotation_angle=90, pages=[1])
    print(f"  {res_rot}")
    # Verify that the PDF's internal rotation metadata equals 90 degrees
    reader = PdfReader(str(rotated_out))
    assert reader.pages[0].rotation == 90, "Page 1 was not rotated"
    print("✔ rotate_pages passed")

    # -----------------------------------------------------------------------
    # Skill 3: Merge PDFs
    # -----------------------------------------------------------------------
    print(f"\n--- Skill 3: Merge PDFs (Targets: {[p.name for p in (test_pdfs[:3] if test_pdfs else [doc_a, doc_b])]}) ---")
    merge_inputs = test_pdfs[:3] if len(test_pdfs) >= 2 else [doc_a, doc_b]
    merged_out = RESULTS_DIR / "merged_test_output.pdf"
    res_merge = merge_pdfs(merge_inputs, merged_out)
    print(f"  {res_merge}")
    # Verify that merged file page count equals the sum of all inputs
    expected_pages = sum(len(PdfReader(str(p)).pages) for p in merge_inputs)
    reader = PdfReader(str(merged_out))
    assert len(reader.pages) == expected_pages, f"Expected {expected_pages} pages, got {len(reader.pages)}"
    print("✔ merge_pdfs passed")

    # -----------------------------------------------------------------------
    # Skill 4: Split / Extract Pages
    # -----------------------------------------------------------------------
    print(f"\n--- Skill 4: Split / Extract Pages (Target: {doc_a.name}) ---")
    split_out = RESULTS_DIR / f"{doc_a.stem}_page_1.pdf"
    res_split = split_pdf(doc_a, split_out, page_range="1")
    print(f"  {res_split}")
    # Verify that the extracted document has exactly 1 page
    reader = PdfReader(str(split_out))
    assert len(reader.pages) == 1, f"Expected 1 page, got {len(reader.pages)}"
    print("✔ split_pdf passed")

    # -----------------------------------------------------------------------
    # Skill 5: Add Watermark
    # -----------------------------------------------------------------------
    print(f"\n--- Skill 5: Add Watermark (Target: {doc_b.name}) ---")
    watermark_out = RESULTS_DIR / f"{doc_b.stem}_watermarked.pdf"
    res_wm = add_watermark(doc_b, watermark_out, watermark_text="TEST WATERMARK")
    print(f"  {res_wm}")
    assert watermark_out.exists(), "Watermarked output file not found"
    print("✔ add_watermark passed")

    print("\n" + "=" * 65)
    print("ALL 5 PREDEFINED PDF SKILLS TESTED SUCCESSFULLY!")
    print(f"Output files saved to: {RESULTS_DIR}")
    print("=" * 65)


def test_gemini_model_loader():
    """
    Tests the AI model loader:
    1. Checks if GEMINI_API_KEY was found in .env (without printing the secret).
    2. Verifies which model and SDK were loaded.
    3. Sends a lightweight ping prompt to Google's API to confirm connectivity.
    """
    print("\n" + "=" * 65)
    print("STEP 2: TESTING GEMINI MODEL LOADER (SECRET FILE INTEGRATION)")
    print("=" * 65)

    model = GeminiPDFModel()
    status = model.get_status_info()

    print(f"• Secret Key Configured : {status['configured']}")
    print(f"• API Key (Masked)      : {status['api_key_masked']}")
    print(f"• Model Selected        : {status['model_name']}")
    print(f"• Detected SDK          : {status['sdk_detected']}")

    if not status["configured"]:
        print("\n[INFO] Gemini API key not yet configured in the secret file '.env'.")
        print("To load your Gemini model:")
        print("  1. Create or edit '.env' in the project root.")
        print("  2. Add: GEMINI_API_KEY=your_key_here")
        print("  (Note: Antigravity cannot and will not read your secret file.)")
    else:
        print("\nTesting connection with Gemini...")
        conn_res = model.verify_connection()
        if conn_res.get("success"):
            print("✔ Connection successful!")
            print(f"  Gemini response: {conn_res.get('response')}")
        else:
            print(f"❌ Connection failed: {conn_res.get('error')}")


# ---------------------------------------------------------------------------
# Script Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_predefined_skills()
    test_gemini_model_loader()
