"""
skills/pdf_skills.py
=============================================================================
Predefined PDF Modification Skills

PURPOSE:
--------
This module contains the actual PDF manipulation functions. Each function
is decorated with `@registry.register(...)`, making it automatically discoverable
by the CLI and by the Gemini AI orchestrator.

LIBRARIES USED:
---------------
- `pypdf`: Fast, pure-Python library for reading, writing, rotating, splitting,
  and merging PDF documents without requiring system binaries.
- `reportlab`: PDF drawing toolkit used to dynamically generate watermarks
  in memory with precise rotation, transparency, and scaling.
=============================================================================
"""

import io
import os
from typing import List, Optional, Union
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

from .base import registry


# ---------------------------------------------------------------------------
# Internal Helper Functions
# ---------------------------------------------------------------------------

def _ensure_dir(filepath: str):
    """
    Ensures that the parent directory for a target file path exists.
    If the directory does not exist, `os.makedirs` creates it recursively.
    Prevents 'FileNotFoundError' when writing to new folders like 'output/'.
    """
    parent = os.path.dirname(filepath)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _parse_page_ranges(range_str: str, max_pages: int) -> List[int]:
    """
    Converts human-friendly page strings like "1-3, 5" into 0-based Python indices.

    Examples:
    ---------
    - "1-3, 5" with max_pages=5 -> [0, 1, 2, 4]
    - "2" with max_pages=3      -> [1]

    :param range_str: User-supplied range string (e.g. '1-2', '1,3,5').
    :param max_pages: Total number of pages in the document to prevent out-of-bounds.
    :return: Sorted list of 0-based page index integers.
    """
    pages = set()
    # Split by comma to handle multiple parts (e.g. "1-3", "5")
    parts = [p.strip() for p in range_str.split(",") if p.strip()]
    
    for part in parts:
        if "-" in part:
            # Handle page range format "start-end"
            start_str, end_str = part.split("-", 1)
            start = max(1, int(start_str.strip()))
            end = min(max_pages, int(end_str.strip()))
            for p in range(start, end + 1):
                pages.add(p - 1)  # Convert 1-based human page to 0-based index
        else:
            # Handle single page number "5"
            p = int(part.strip())
            if 1 <= p <= max_pages:
                pages.add(p - 1)
                
    return sorted(list(pages))


# ---------------------------------------------------------------------------
# Skill 1: Extract Text
# ---------------------------------------------------------------------------

@registry.register(
    name="extract_text",
    description="Extracts plain text content from a PDF file. Can extract from all pages or a specific subset of pages (1-indexed)."
)
def extract_text(input_pdf_path: Union[str, os.PathLike], pages: Optional[List[int]] = None) -> str:
    """
    Reads a PDF file and extracts text content into formatted plain text.

    :param input_pdf_path: Filepath to the PDF document.
    :param pages: Optional list of 1-based page numbers (e.g. [1, 2]).
                  If None, extracts text from all pages.
    :return: Extracted text formatted with '--- Page X ---' headers.
    """
    input_pdf_path = str(input_pdf_path)
    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")

    # Load the PDF file for reading
    reader = PdfReader(input_pdf_path)
    total_pages = len(reader.pages)

    # Determine target page indices (convert 1-indexed input to 0-indexed)
    target_indices = [p - 1 for p in pages if 1 <= p <= total_pages] if pages else list(range(total_pages))

    output = []
    for idx in target_indices:
        # Extract raw text stream from page object
        page_text = reader.pages[idx].extract_text() or ""
        output.append(f"--- Page {idx + 1} ---\n{page_text.strip()}")

    return "\n\n".join(output)


# ---------------------------------------------------------------------------
# Skill 2: Rotate Pages
# ---------------------------------------------------------------------------

@registry.register(
    name="rotate_pages",
    description="Rotates specific or all pages of a PDF by 90, 180, or 270 degrees clockwise and saves to output_pdf_path."
)
def rotate_pages(
    input_pdf_path: Union[str, os.PathLike],
    output_pdf_path: Union[str, os.PathLike],
    rotation_angle: int,
    pages: Optional[List[int]] = None
) -> str:
    """
    Rotates selected pages clockwise and saves the modified PDF to a new file.

    :param input_pdf_path: Path to the original PDF.
    :param output_pdf_path: Destination path for the rotated PDF.
    :param rotation_angle: Clockwise angle in degrees (must be 90, 180, or 270).
    :param pages: Optional list of 1-based page numbers to rotate. If None, rotates all pages.
    :return: Informational success message.
    """
    input_pdf_path = str(input_pdf_path)
    output_pdf_path = str(output_pdf_path)

    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")
    if rotation_angle not in [90, 180, 270]:
        raise ValueError("rotation_angle must be 90, 180, or 270 degrees.")

    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    total_pages = len(reader.pages)
    
    # 0-based indices of pages that should be rotated
    rotate_indices = set(p - 1 for p in pages if 1 <= p <= total_pages) if pages else set(range(total_pages))

    for idx, page in enumerate(reader.pages):
        if idx in rotate_indices:
            # Apply clockwise rotation to page dictionary
            page.rotate(rotation_angle)
        writer.add_page(page)

    # Ensure output folder exists and write the PDF
    _ensure_dir(output_pdf_path)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return f"Successfully rotated {len(rotate_indices)} page(s) by {rotation_angle}° and saved to '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill 3: Merge PDFs
# ---------------------------------------------------------------------------

@registry.register(
    name="merge_pdfs",
    description="Merges multiple PDF files into a single destination PDF file in the order provided."
)
def merge_pdfs(input_pdf_paths: List[Union[str, os.PathLike]], output_pdf_path: Union[str, os.PathLike]) -> str:
    """
    Combines two or more PDF files into a single continuous PDF document.

    :param input_pdf_paths: Ordered list of PDF filepaths to concatenate.
    :param output_pdf_path: Destination path for the unified PDF.
    :return: Informational success message.
    """
    output_pdf_path = str(output_pdf_path)
    input_paths = [str(p) for p in input_pdf_paths]

    if not input_paths:
        raise ValueError("At least one input PDF path is required.")

    writer = PdfWriter()
    total_merged = 0

    # Iterate over each document and append every page to the writer
    for path in input_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF file to merge does not exist: {path}")
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
            total_merged += 1

    _ensure_dir(output_pdf_path)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return f"Successfully merged {len(input_paths)} files ({total_merged} pages) into '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill 4: Split / Extract Pages
# ---------------------------------------------------------------------------

@registry.register(
    name="split_pdf",
    description="Extracts specific pages or ranges (e.g. '1-3, 5') from a PDF into a new PDF."
)
def split_pdf(
    input_pdf_path: Union[str, os.PathLike],
    output_pdf_path: Union[str, os.PathLike],
    page_range: str
) -> str:
    """
    Extracts a subset of pages from a PDF and saves them as a new PDF.

    :param input_pdf_path: Path to source PDF.
    :param output_pdf_path: Destination path for extracted pages.
    :param page_range: 1-indexed range expression like '1-2' or '1, 3'.
    :return: Informational success message.
    """
    input_pdf_path = str(input_pdf_path)
    output_pdf_path = str(output_pdf_path)

    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")

    reader = PdfReader(input_pdf_path)
    indices = _parse_page_ranges(page_range, len(reader.pages))

    if not indices:
        raise ValueError(f"No valid pages found matching range '{page_range}'. Total pages: {len(reader.pages)}")

    # Add only the targeted pages into the writer
    writer = PdfWriter()
    for idx in indices:
        writer.add_page(reader.pages[idx])

    _ensure_dir(output_pdf_path)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return f"Successfully extracted pages ({', '.join(str(i + 1) for i in indices)}) into '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill 5: Add Watermark
# ---------------------------------------------------------------------------

@registry.register(
    name="add_watermark",
    description="Adds a semi-transparent text watermark across the pages of a PDF and saves the result."
)
def add_watermark(
    input_pdf_path: Union[str, os.PathLike],
    output_pdf_path: Union[str, os.PathLike],
    watermark_text: str,
    pages: Optional[List[int]] = None
) -> str:
    """
    Draws a semi-transparent diagonal text watermark across pages.

    Technique:
    ----------
    1. Uses ReportLab to generate an in-memory PDF page (`io.BytesIO`) matching
       the exact dimensions (width x height) of each target page.
    2. Translates coordinate space to the page center and rotates 45 degrees.
    3. Merges the transparent watermark layer over the original page content.

    :param input_pdf_path: Path to the input PDF file.
    :param output_pdf_path: Destination path for the watermarked PDF.
    :param watermark_text: The watermark stamp (e.g. 'CONFIDENTIAL', 'SAMPLE').
    :param pages: Optional list of 1-based page numbers. Defaults to all pages.
    :return: Informational success message.
    """
    input_pdf_path = str(input_pdf_path)
    output_pdf_path = str(output_pdf_path)

    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")

    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    total_pages = len(reader.pages)
    target_indices = set(p - 1 for p in pages if 1 <= p <= total_pages) if pages else set(range(total_pages))

    for idx, page in enumerate(reader.pages):
        if idx in target_indices:
            # Measure target page dimensions in PDF points (72 points = 1 inch)
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)

            # In-memory buffer to hold the watermark PDF layer
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(width, height))
            can.saveState()
            
            # Configure semi-transparent gray font
            can.setFont("Helvetica-Bold", 40)
            can.setFillColor(Color(0.7, 0.7, 0.7, alpha=0.35))
            
            # Move origin to page center and tilt 45 degrees
            can.translate(width / 2.0, height / 2.0)
            can.rotate(45)
            can.drawCentredString(0, 0, watermark_text)
            
            can.restoreState()
            can.save()

            # Read back watermark from memory buffer
            packet.seek(0)
            watermark_pdf_reader = PdfReader(packet)
            watermark_page = watermark_pdf_reader.pages[0]

            # Merge watermark layer on top of original page
            page.merge_page(watermark_page)

        writer.add_page(page)

    _ensure_dir(output_pdf_path)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return f"Successfully added watermark '{watermark_text}' to {len(target_indices)} page(s) in '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill 6: Delete Pages
# ---------------------------------------------------------------------------

@registry.register(
    name="delete_pages",
    description="Deletes specific 1-indexed pages (e.g. [2] or [1, 3]) from a PDF and saves the remaining pages to output_pdf_path."
)
def delete_pages(
    input_pdf_path: Union[str, os.PathLike],
    output_pdf_path: Union[str, os.PathLike],
    pages_to_delete: List[int]
) -> str:
    """
    Deletes specified pages from a PDF document.

    :param input_pdf_path: Path to the input PDF file.
    :param output_pdf_path: Destination path for the modified PDF.
    :param pages_to_delete: List of 1-based page numbers to remove (e.g. [2]).
    :return: Informational success message.
    """
    input_pdf_path = str(input_pdf_path)
    output_pdf_path = str(output_pdf_path)

    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")

    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    total_pages = len(reader.pages)
    
    # Convert 1-indexed delete requests to 0-indexed internal indices
    delete_indices = set(p - 1 for p in pages_to_delete if 1 <= p <= total_pages)

    if not delete_indices:
        raise ValueError(f"No matching pages found in delete list {pages_to_delete}. Total pages: {total_pages}")

    if len(delete_indices) >= total_pages:
        raise ValueError("Cannot delete all pages of the PDF. At least 1 page must remain.")

    # Retain all pages that are NOT in the deletion list
    kept_count = 0
    for idx, page in enumerate(reader.pages):
        if idx not in delete_indices:
            writer.add_page(page)
            kept_count += 1

    _ensure_dir(output_pdf_path)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return f"Successfully deleted {len(delete_indices)} page(s), kept {kept_count} page(s) in '{output_pdf_path}'."
