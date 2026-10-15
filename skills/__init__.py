"""
skills/__init__.py
=============================================================================
PDF Modification Skills Package

PURPOSE:
--------
Exports the predefined PDF modification skills and the central registry:
- `registry`: Global SkillRegistry instance tracking all tools.
- `extract_text`: Plain text extraction from pages.
- `rotate_pages`: Clockwise page rotation (90, 180, 270 degrees).
- `merge_pdfs`: Concatenates multiple PDF files into one.
- `split_pdf`: Extracts page ranges into a new document.
- `add_watermark`: Semi-transparent diagonal text stamping.
- `delete_pages`: Deletes specified pages from a document.
=============================================================================
"""

from .base import registry, Skill, SkillRegistry
from .pdf_skills import (
    extract_text,
    rotate_pages,
    merge_pdfs,
    split_pdf,
    add_watermark,
    delete_pages,
)

__all__ = [
    "registry",
    "Skill",
    "SkillRegistry",
    "extract_text",
    "rotate_pages",
    "merge_pdfs",
    "split_pdf",
    "add_watermark",
    "delete_pages",
]
