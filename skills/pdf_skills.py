"""
skills/pdf_skills.py
=============================================================================
Predefined PDF Modification Skills

PURPOSE:
--------
This module contains the actual PDF manipulation functions. Each function
is decorated with `@registry.register(...)`, making it automatically discoverable
by the CLI, the Gemini orchestrator (`main.py`) and the Claude agent (`pdf_agent.py`).

Conventions:
------------
- Input files are `input_*_path(s)` parameters, output files `output_*_path(s)`.
- Page parameters are 1-based and accept a list ([1, 3]) or a spec string ('1-3,5,7-').
- Every reading skill accepts an optional `password` for encrypted inputs.
- Every write goes through `claim_output`, so a sandbox (`skills/sandbox.py`)
  can confine and track outputs when one is active.

LIBRARIES USED:
---------------
- `pypdf`: Fast, pure-Python library for reading, writing, rotating, splitting,
  merging and encrypting PDF documents without requiring system binaries.
- `reportlab`: PDF drawing toolkit used to dynamically generate watermarks
  in memory with precise rotation, transparency, and scaling.
=============================================================================
"""

import io
import os
from pathlib import Path
from typing import List, Literal, Optional, Union
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

from .base import registry, SkillError
from .pages import parse_page_ranges
from .sandbox import claim_output

PathLike = Union[str, os.PathLike]
Pages = Optional[Union[List[int], str]]


# ---------------------------------------------------------------------------
# Internal Helper Functions
# ---------------------------------------------------------------------------

def _open_pdf(input_pdf_path: PathLike, password: Optional[str] = None) -> PdfReader:
    """Opens a PDF for reading, decrypting it with `password` when necessary."""
    input_pdf_path = str(input_pdf_path)
    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")
    reader = PdfReader(input_pdf_path)
    if reader.is_encrypted:
        if not password or not reader.decrypt(password):
            raise SkillError(f"{Path(input_pdf_path).name} is encrypted; supply a valid 'password'")
    return reader


def _write_pdf(writer: PdfWriter, output_pdf_path: PathLike) -> str:
    """Writes `writer` to `output_pdf_path` (sandbox-checked) and returns the path."""
    path = claim_output(output_pdf_path)
    with open(path, "wb") as f:
        writer.write(f)
    return path


# ---------------------------------------------------------------------------
# Skill: Extract Text
# ---------------------------------------------------------------------------

@registry.register(
    name="extract_text",
    description="Extracts plain text content from a PDF file, from all pages or a subset of pages (1-indexed). "
                "Optionally saves the text to a .txt file. Does not OCR scanned pages.",
    destructive=False,
)
def extract_text(
    input_pdf_path: PathLike,
    pages: Pages = None,
    output_txt_path: Optional[PathLike] = None,
    password: Optional[str] = None,
) -> str:
    """
    Reads a PDF file and extracts text content into formatted plain text.

    :param input_pdf_path: Path to the PDF document.
    :param pages: Optional 1-based pages, as a list (e.g. [1, 2]) or a spec string (e.g. '1-3,5,7-'). Omit for all pages.
    :param output_txt_path: Optional .txt file to save the extracted text to.
    :param password: Password if the input PDF is encrypted.
    :return: Extracted text formatted with '--- Page X ---' headers (or a summary if saved to a file).
    """
    reader = _open_pdf(input_pdf_path, password)
    target_indices = parse_page_ranges(pages, len(reader.pages))

    output = []
    has_text = False
    for idx in target_indices:
        # Extract raw text stream from page object
        page_text = (reader.pages[idx].extract_text() or "").strip()
        has_text = has_text or bool(page_text)
        output.append(f"--- Page {idx + 1} ---\n{page_text}")

    text = "\n\n".join(output)
    if target_indices and not has_text:
        text += "\n[No text layer found - the PDF may be scanned and need OCR]"

    if output_txt_path:
        path = claim_output(output_txt_path)
        Path(path).write_text(text, encoding="utf-8")
        return f"Wrote text of {len(target_indices)} page(s) to '{path}'."
    return text


# ---------------------------------------------------------------------------
# Skill: Rotate Pages
# ---------------------------------------------------------------------------

@registry.register(
    name="rotate_pages",
    description="Rotates specific or all pages of a PDF by 90, 180, or 270 degrees clockwise and saves to output_pdf_path."
)
def rotate_pages(
    input_pdf_path: PathLike,
    output_pdf_path: PathLike,
    rotation_angle: Literal[90, 180, 270],
    pages: Pages = None,
    password: Optional[str] = None,
) -> str:
    """
    Rotates selected pages clockwise and saves the modified PDF to a new file.

    :param input_pdf_path: Path to the original PDF.
    :param output_pdf_path: Destination path (.pdf) for the rotated PDF.
    :param rotation_angle: Clockwise angle in degrees (must be 90, 180, or 270).
    :param pages: Optional 1-based pages to rotate, as a list or spec string ('1-3,5,7-'). Omit for all pages.
    :param password: Password if the input PDF is encrypted.
    :return: Informational success message.
    """
    if rotation_angle not in [90, 180, 270]:
        raise ValueError("rotation_angle must be 90, 180, or 270 degrees.")

    reader = _open_pdf(input_pdf_path, password)
    writer = PdfWriter()

    # 0-based indices of pages that should be rotated
    rotate_indices = set(parse_page_ranges(pages, len(reader.pages)))

    for idx, page in enumerate(reader.pages):
        if idx in rotate_indices:
            # Apply clockwise rotation to page dictionary
            page.rotate(rotation_angle)
        writer.add_page(page)

    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully rotated {len(rotate_indices)} page(s) by {rotation_angle}° and saved to '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill: Merge PDFs
# ---------------------------------------------------------------------------

@registry.register(
    name="merge_pdfs",
    description="Merges multiple PDF files into a single destination PDF file in the order provided."
)
def merge_pdfs(
    input_pdf_paths: List[PathLike],
    output_pdf_path: PathLike,
    password: Optional[str] = None,
) -> str:
    """
    Combines two or more PDF files into a single continuous PDF document.

    :param input_pdf_paths: Ordered list of PDF filepaths to concatenate.
    :param output_pdf_path: Destination path (.pdf) for the unified PDF.
    :param password: Password if the input PDFs are encrypted.
    :return: Informational success message.
    """
    input_paths = [str(p) for p in input_pdf_paths]

    if not input_paths:
        raise ValueError("At least one input PDF path is required.")

    writer = PdfWriter()
    total_merged = 0

    # Iterate over each document and append every page to the writer
    for path in input_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF file to merge does not exist: {path}")
        for page in _open_pdf(path, password).pages:
            writer.add_page(page)
            total_merged += 1

    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully merged {len(input_paths)} files ({total_merged} pages) into '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill: Split / Extract Pages
# ---------------------------------------------------------------------------

@registry.register(
    name="split_pdf",
    description="Extracts specific pages or ranges (e.g. '1-3, 5', '7-') from a PDF into a new PDF."
)
def split_pdf(
    input_pdf_path: PathLike,
    output_pdf_path: PathLike,
    page_range: str,
    password: Optional[str] = None,
) -> str:
    """
    Extracts a subset of pages from a PDF and saves them as a new PDF.

    :param input_pdf_path: Path to source PDF.
    :param output_pdf_path: Destination path (.pdf) for extracted pages.
    :param page_range: 1-indexed range expression like '1-2', '1, 3' or '7-'.
    :param password: Password if the input PDF is encrypted.
    :return: Informational success message.
    """
    reader = _open_pdf(input_pdf_path, password)
    indices = parse_page_ranges(page_range, len(reader.pages))

    if not indices:
        raise ValueError(f"No valid pages found matching range '{page_range}'. Total pages: {len(reader.pages)}")

    # Add only the targeted pages into the writer
    writer = PdfWriter()
    for idx in indices:
        writer.add_page(reader.pages[idx])

    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully extracted pages ({', '.join(str(i + 1) for i in indices)}) into '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill: Split Into Parts
# ---------------------------------------------------------------------------

@registry.register(
    name="split_pdf_into_parts",
    description="Splits a PDF into multiple PDFs of N pages each, named '<output stem>_part<N>.pdf'."
)
def split_pdf_into_parts(
    input_pdf_path: PathLike,
    output_pdf_path: PathLike,
    pages_per_file: int = 1,
    password: Optional[str] = None,
) -> str:
    """
    Splits a PDF into consecutive chunks of `pages_per_file` pages.

    :param input_pdf_path: Path to source PDF.
    :param output_pdf_path: Base output name (.pdf); parts are written next to it as '<stem>_part1.pdf', ...
    :param pages_per_file: Number of pages per output file (default 1).
    :param password: Password if the input PDF is encrypted.
    :return: Informational success message.
    """
    if pages_per_file < 1:
        raise SkillError("pages_per_file must be >= 1")

    reader = _open_pdf(input_pdf_path, password)
    base = Path(output_pdf_path)
    outputs = []
    for i in range(0, len(reader.pages), pages_per_file):
        writer = PdfWriter()
        for page in reader.pages[i: i + pages_per_file]:
            writer.add_page(page)
        part = base.with_name(f"{base.stem}_part{i // pages_per_file + 1}.pdf")
        outputs.append(Path(_write_pdf(writer, part)).name)

    return f"Successfully split into {len(outputs)} file(s): {', '.join(outputs)}."


# ---------------------------------------------------------------------------
# Skill: Add Watermark
# ---------------------------------------------------------------------------

@registry.register(
    name="add_watermark",
    description="Adds a semi-transparent diagonal text watermark (e.g. DRAFT, CONFIDENTIAL) across the pages of a PDF and saves the result."
)
def add_watermark(
    input_pdf_path: PathLike,
    output_pdf_path: PathLike,
    watermark_text: str,
    pages: Pages = None,
    opacity: float = 0.35,
    password: Optional[str] = None,
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
    :param output_pdf_path: Destination path (.pdf) for the watermarked PDF.
    :param watermark_text: The watermark stamp (e.g. 'CONFIDENTIAL', 'SAMPLE').
    :param pages: Optional 1-based pages, as a list or spec string ('1-3,5,7-'). Omit for all pages.
    :param opacity: Watermark opacity from 0 to 1 (default 0.35).
    :param password: Password if the input PDF is encrypted.
    :return: Informational success message.
    """
    reader = _open_pdf(input_pdf_path, password)
    writer = PdfWriter()
    target_indices = set(parse_page_ranges(pages, len(reader.pages)))

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
            can.setFillColor(Color(0.7, 0.7, 0.7, alpha=float(opacity)))

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

    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully added watermark '{watermark_text}' to {len(target_indices)} page(s) in '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill: Delete Pages
# ---------------------------------------------------------------------------

@registry.register(
    name="delete_pages",
    description="Deletes specific 1-indexed pages (e.g. [2] or [1, 3]) from a PDF and saves the remaining pages to output_pdf_path."
)
def delete_pages(
    input_pdf_path: PathLike,
    output_pdf_path: PathLike,
    pages_to_delete: Union[List[int], str],
    password: Optional[str] = None,
) -> str:
    """
    Deletes specified pages from a PDF document.

    :param input_pdf_path: Path to the input PDF file.
    :param output_pdf_path: Destination path (.pdf) for the modified PDF.
    :param pages_to_delete: 1-based pages to remove, as a list (e.g. [2]) or spec string (e.g. '2-4').
    :param password: Password if the input PDF is encrypted.
    :return: Informational success message.
    """
    reader = _open_pdf(input_pdf_path, password)
    writer = PdfWriter()
    total_pages = len(reader.pages)

    # Convert 1-indexed delete requests to 0-indexed internal indices
    delete_indices = set(parse_page_ranges(pages_to_delete, total_pages)) if pages_to_delete else set()

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

    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully deleted {len(delete_indices)} page(s), kept {kept_count} page(s) in '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill: Encrypt / Decrypt
# ---------------------------------------------------------------------------

@registry.register(
    name="encrypt_pdf",
    description="Password-protects a PDF (AES-256) and saves it to output_pdf_path."
)
def encrypt_pdf(
    input_pdf_path: PathLike,
    output_pdf_path: PathLike,
    user_password: str,
    owner_password: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """
    Encrypts a PDF with AES-256.

    :param input_pdf_path: Path to the input PDF file.
    :param output_pdf_path: Destination path (.pdf) for the encrypted PDF.
    :param user_password: Password required to open the output PDF.
    :param owner_password: Optional owner password (defaults to user_password).
    :param password: Password if the input PDF is already encrypted.
    :return: Informational success message.
    """
    reader = _open_pdf(input_pdf_path, password)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password, owner_password or user_password, algorithm="AES-256")
    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully encrypted PDF into '{output_pdf_path}'."


@registry.register(
    name="decrypt_pdf",
    description="Removes password protection from a PDF (requires the password) and saves it to output_pdf_path."
)
def decrypt_pdf(input_pdf_path: PathLike, output_pdf_path: PathLike, password: str) -> str:
    """
    Writes an unencrypted copy of a password-protected PDF.

    :param input_pdf_path: Path to the encrypted PDF file.
    :param output_pdf_path: Destination path (.pdf) for the decrypted PDF.
    :param password: Password of the input PDF.
    :return: Informational success message.
    """
    reader = _open_pdf(input_pdf_path, password)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    output_pdf_path = _write_pdf(writer, output_pdf_path)
    return f"Successfully decrypted PDF into '{output_pdf_path}'."


# ---------------------------------------------------------------------------
# Skill: PDF Info
# ---------------------------------------------------------------------------

@registry.register(
    name="pdf_info",
    description="Reports page count, page size and metadata (title, author) of a PDF.",
    destructive=False,
)
def pdf_info(input_pdf_path: PathLike, password: Optional[str] = None) -> str:
    """
    Summarises basic properties of a PDF.

    :param input_pdf_path: Path to the PDF document.
    :param password: Password if the input PDF is encrypted.
    :return: One-line summary.
    """
    name = Path(input_pdf_path).name
    if not os.path.exists(str(input_pdf_path)):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")
    reader = PdfReader(str(input_pdf_path))
    if reader.is_encrypted and not (password and reader.decrypt(password)):
        return f"{name}: encrypted, {'wrong' if password else 'no'} password"
    meta = reader.metadata or {}
    width, height = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    return (f"{name}: {len(reader.pages)} pages, {float(width):.0f}x{float(height):.0f} pt, "
            f"title={meta.get('/Title')!r}, author={meta.get('/Author')!r}")


# ---------------------------------------------------------------------------
# Skill: Clarify
# ---------------------------------------------------------------------------

@registry.register(
    name="clarify",
    description="Use ONLY when the request is ambiguous or a required value (file, password, page range) "
                "cannot be inferred. Asks the user a question instead of guessing.",
    destructive=False,
)
def clarify(question: str) -> str:
    """
    Stops the plan and surfaces a question to the user.

    :param question: What you need to know from the user.
    """
    raise SkillError(f"Need more info: {question}")
