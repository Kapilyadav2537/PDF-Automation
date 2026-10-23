"""
skills/__init__.py
=============================================================================
PDF Modification Skills Package

PURPOSE:
--------
Single source of truth for PDF skills, shared by the Gemini (`main.py`) and
Claude (`pdf_agent.py`) backends:
- `registry`: Global SkillRegistry instance tracking all tools.
- `Ctx`: Sandboxed execution context (inputs in workdir, outputs in outdir).
- `parse_page_ranges`: Shared 1-based page-spec parser.
- `extract_text`, `rotate_pages`, `merge_pdfs`, `split_pdf`, `split_pdf_into_parts`,
  `add_watermark`, `delete_pages`, `encrypt_pdf`, `decrypt_pdf`, `pdf_info`, `clarify`.
=============================================================================
"""

from .base import registry, Skill, SkillError, SkillRegistry
from .pages import parse_page_ranges
from .sandbox import Ctx, claim_output, mask_secrets
from .pdf_skills import (
    extract_text,
    rotate_pages,
    merge_pdfs,
    split_pdf,
    split_pdf_into_parts,
    add_watermark,
    delete_pages,
    encrypt_pdf,
    decrypt_pdf,
    pdf_info,
    clarify,
)

__all__ = [
    "registry",
    "Skill",
    "SkillError",
    "SkillRegistry",
    "Ctx",
    "claim_output",
    "mask_secrets",
    "parse_page_ranges",
    "extract_text",
    "rotate_pages",
    "merge_pdfs",
    "split_pdf",
    "split_pdf_into_parts",
    "add_watermark",
    "delete_pages",
    "encrypt_pdf",
    "decrypt_pdf",
    "pdf_info",
    "clarify",
]
