"""
skills/pages.py
=============================================================================
Shared 1-based page-range parsing used by every skill and backend.
=============================================================================
"""

from typing import Iterable, List, Optional, Union

from .base import SkillError

PageSpec = Optional[Union[str, int, Iterable[Union[int, str]]]]


def parse_page_ranges(spec: PageSpec, max_pages: int, strict: bool = False) -> List[int]:
    """
    Converts a 1-based page spec into 0-based page indices.

    Accepted specs:
    ---------------
    - None, "", "all", or an empty list -> every page
    - "1-3, 5"  -> pages 1, 2, 3 and 5
    - "7-" / "-3" -> open-ended ranges (page 7 to the end / page 1 to 3)
    - 5 or [1, 3] -> explicit page numbers

    Modes:
    ------
    - strict=False: out-of-range pages are clamped/ignored; result is sorted and de-duplicated.
    - strict=True:  out-of-range or inverted ranges raise SkillError; order and duplicates are kept.

    Unparseable parts always raise SkillError (a ValueError subclass).

    :param spec: Page specification (see above).
    :param max_pages: Total number of pages in the document.
    :param strict: Whether to reject out-of-range pages instead of skipping them.
    :return: List of 0-based page indices.
    """
    if spec is None or (isinstance(spec, str) and spec.strip().lower() in ("", "all")):
        return list(range(max_pages))
    if isinstance(spec, (int, str)):
        parts = str(spec).split(",")
    else:
        parts = [str(p) for p in spec]
        if not parts:
            return list(range(max_pages))

    indices: List[int] = []
    for raw in parts:
        part = raw.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start = int(a) if a.strip() else 1
                end = int(b) if b.strip() else max_pages
            else:
                start = end = int(part)
        except ValueError:
            raise SkillError(f"Bad page spec: '{part}'")

        if strict:
            if start < 1 or end > max_pages or start > end:
                raise SkillError(f"Pages '{part}' out of range (document has {max_pages} pages)")
        else:
            start, end = max(1, start), min(max_pages, end)
        indices.extend(range(start - 1, end))

    return indices if strict else sorted(set(indices))
