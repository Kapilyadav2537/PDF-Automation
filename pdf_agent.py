#!/usr/bin/env python3
"""
pdf_agent v1 - natural language -> PDF skill activation with user-provided parameters.

Flow:  request  ->  LLM picks skill(s) + args (tool use)  ->  merge with your
       explicit --param overrides  ->  validate  ->  show plan  ->  confirm  ->  run

Examples:
  export ANTHROPIC_API_KEY=...
  python pdf_agent.py "merge report.pdf and appendix.pdf into final.pdf"
  python pdf_agent.py "rotate the first 3 pages of scan.pdf by 90" --dry-run
  python pdf_agent.py "split book.pdf" --param pages_per_file=10 --yes
  python pdf_agent.py --list-skills
  python pdf_agent.py --plan '[{"skill":"info","args":{"file":"a.pdf"}}]'   # no LLM

Requires: pip install pypdf reportlab anthropic   (pdfplumber optional, for layout text)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pypdf import PdfReader, PdfWriter

VERSION = "1.0.0"
DEFAULT_MODEL = os.environ.get("PDF_AGENT_MODEL", "claude-sonnet-5-5")


class SkillError(Exception):
    """Raised for bad parameters or failed operations (shown to the user, not a crash)."""


# --------------------------------------------------------------------------- #
# Execution context + helpers
# --------------------------------------------------------------------------- #
@dataclass
class Ctx:
    workdir: Path
    outdir: Path
    overwrite: bool = False

    def src(self, name: str) -> Path:
        """Resolve an input file; must live inside workdir."""
        p = (self.workdir / name).resolve()
        if self.workdir not in p.parents and p != self.workdir:
            raise SkillError(f"'{name}' is outside the working directory")
        if not p.is_file():
            raise SkillError(f"File not found: {name}")
        return p

    def dst(self, name: str) -> Path:
        """Resolve an output file; always written into outdir (basename only)."""
        p = self.outdir / Path(name).name
        if p.exists() and not self.overwrite:
            raise SkillError(f"{p.name} already exists (use --overwrite)")
        self.outdir.mkdir(parents=True, exist_ok=True)
        return p


def parse_pages(spec, n: int) -> list[int]:
    """'1-3,5,7-' (1-based) -> 0-based indices. None/'all' -> every page."""
    if spec in (None, "", "all"):
        return list(range(n))
    idx: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start, end = int(a) if a else 1, int(b) if b else n
            else:
                start = end = int(part)
        except ValueError:
            raise SkillError(f"Bad page spec: '{part}'")
        if start < 1 or end > n or start > end:
            raise SkillError(f"Pages '{part}' out of range (document has {n} pages)")
        idx.extend(range(start - 1, end))
    return idx


def open_pdf(ctx: Ctx, name: str, password: str | None = None) -> PdfReader:
    r = PdfReader(str(ctx.src(name)))
    if r.is_encrypted:
        if not password or not r.decrypt(password):
            raise SkillError(f"{name} is encrypted; supply a valid 'password'")
    return r


def save(writer: PdfWriter, path: Path) -> str:
    with open(path, "wb") as f:
        writer.write(f)
    return path.name


# --------------------------------------------------------------------------- #
# Skills (handlers return {"message": str, "outputs": [names]})
# --------------------------------------------------------------------------- #
def skill_merge(ctx: Ctx, a: dict) -> dict:
    files = a["files"]
    if len(files) < 2:
        raise SkillError("merge needs at least 2 files")
    w = PdfWriter()
    for f in files:
        for p in open_pdf(ctx, f, a.get("password")).pages:
            w.add_page(p)
    out = save(w, ctx.dst(a.get("output", "merged.pdf")))
    return {"message": f"Merged {len(files)} files into {out}", "outputs": [out]}


def skill_split(ctx: Ctx, a: dict) -> dict:
    r = open_pdf(ctx, a["file"], a.get("password"))
    step = int(a.get("pages_per_file", 1))
    if step < 1:
        raise SkillError("pages_per_file must be >= 1")
    stem = Path(a["file"]).stem
    outs = []
    for i in range(0, len(r.pages), step):
        w = PdfWriter()
        for p in r.pages[i : i + step]:
            w.add_page(p)
        outs.append(save(w, ctx.dst(f"{stem}_part{i // step + 1}.pdf")))
    return {"message": f"Split into {len(outs)} files", "outputs": outs}


def skill_extract_pages(ctx: Ctx, a: dict) -> dict:
    r = open_pdf(ctx, a["file"], a.get("password"))
    idx = parse_pages(a["pages"], len(r.pages))
    w = PdfWriter()
    for i in idx:
        w.add_page(r.pages[i])
    out = save(w, ctx.dst(a.get("output", f"{Path(a['file']).stem}_extract.pdf")))
    return {"message": f"Extracted {len(idx)} page(s) into {out}", "outputs": [out]}


def skill_rotate(ctx: Ctx, a: dict) -> dict:
    r = open_pdf(ctx, a["file"], a.get("password"))
    targets = set(parse_pages(a.get("pages"), len(r.pages)))
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i in targets:
            p.rotate(int(a["degrees"]))
        w.add_page(p)
    out = save(w, ctx.dst(a.get("output", f"{Path(a['file']).stem}_rotated.pdf")))
    return {"message": f"Rotated {len(targets)} page(s) by {a['degrees']}°", "outputs": [out]}


def skill_extract_text(ctx: Ctx, a: dict) -> dict:
    r = open_pdf(ctx, a["file"], a.get("password"))
    idx = parse_pages(a.get("pages"), len(r.pages))
    text = "\n\n".join(f"--- Page {i + 1} ---\n{r.pages[i].extract_text() or ''}" for i in idx)
    if not text.replace("-", "").strip() or all(not (r.pages[i].extract_text() or "").strip() for i in idx):
        text += "\n[No text layer found - the PDF may be scanned and need OCR]"
    if a.get("output"):
        p = ctx.dst(a["output"])
        p.write_text(text, encoding="utf-8")
        return {"message": f"Wrote text of {len(idx)} page(s) to {p.name}", "outputs": [p.name]}
    return {"message": text[:4000] + ("\n...[truncated]" if len(text) > 4000 else ""), "outputs": []}


def skill_encrypt(ctx: Ctx, a: dict) -> dict:
    r = open_pdf(ctx, a["file"], a.get("password"))
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    w.encrypt(a["user_password"], a.get("owner_password") or a["user_password"], algorithm="AES-256")
    out = save(w, ctx.dst(a.get("output", f"{Path(a['file']).stem}_locked.pdf")))
    return {"message": f"Encrypted -> {out}", "outputs": [out]}


def skill_decrypt(ctx: Ctx, a: dict) -> dict:
    r = open_pdf(ctx, a["file"], a["password"])
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    out = save(w, ctx.dst(a.get("output", f"{Path(a['file']).stem}_unlocked.pdf")))
    return {"message": f"Decrypted -> {out}", "outputs": [out]}


def skill_info(ctx: Ctx, a: dict) -> dict:
    r = PdfReader(str(ctx.src(a["file"])))
    if r.is_encrypted and not (a.get("password") and r.decrypt(a["password"])):
        return {"message": f"{a['file']}: encrypted, {'wrong' if a.get('password') else 'no'} password", "outputs": []}
    m = r.metadata or {}
    w, h = r.pages[0].mediabox.width, r.pages[0].mediabox.height
    msg = (f"{a['file']}: {len(r.pages)} pages, {float(w):.0f}x{float(h):.0f} pt, "
           f"title={m.get('/Title')!r}, author={m.get('/Author')!r}")
    return {"message": msg, "outputs": []}


def skill_watermark_text(ctx: Ctx, a: dict) -> dict:
    from reportlab.pdfgen import canvas

    r = open_pdf(ctx, a["file"], a.get("password"))
    targets = set(parse_pages(a.get("pages"), len(r.pages)))
    opacity = float(a.get("opacity", 0.15))
    w = PdfWriter()
    for i, page in enumerate(r.pages):
        if i in targets:
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(pw, ph))
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.setFillAlpha(opacity)
            c.setFont("Helvetica-Bold", min(pw, ph) / 8)
            c.translate(pw / 2, ph / 2)
            c.rotate(45)
            c.drawCentredString(0, 0, a["text"])
            c.save()
            buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
        w.add_page(page)
    out = save(w, ctx.dst(a.get("output", f"{Path(a['file']).stem}_watermarked.pdf")))
    return {"message": f"Watermarked {len(targets)} page(s) -> {out}", "outputs": [out]}


def skill_clarify(ctx: Ctx, a: dict) -> dict:
    raise SkillError(f"Need more info: {a['question']}")


# --------------------------------------------------------------------------- #
# Skill registry - the single source of truth for BOTH the LLM tool schemas
# and local validation.
# --------------------------------------------------------------------------- #
@dataclass
class Skill:
    name: str
    description: str
    properties: dict
    required: list[str]
    handler: Callable[[Ctx, dict], dict]
    destructive: bool = True  # writes files

    @property
    def schema(self) -> dict:
        return {"type": "object", "properties": self.properties, "required": self.required}


S = lambda d: {"type": "string", "description": d}  # noqa: E731
FILE = S("PDF filename, exactly as listed in available files")
OUT = S("Output filename (.pdf). Name it explicitly if a later step will use it")
PAGES = S("Pages, 1-based: '1-3,5,7-'. Omit for all pages")
PWD = S("Password if the input PDF is encrypted")

SKILLS: dict[str, Skill] = {s.name: s for s in [
    Skill("merge", "Combine several PDFs, in order, into one PDF.",
          {"files": {"type": "array", "items": {"type": "string"}, "description": "Input PDFs in desired order"},
           "output": OUT, "password": PWD}, ["files"], skill_merge),
    Skill("split", "Split a PDF into multiple PDFs of N pages each.",
          {"file": FILE, "pages_per_file": {"type": "integer", "description": "Default 1"}, "password": PWD},
          ["file"], skill_split),
    Skill("extract_pages", "Create a new PDF from selected pages of a PDF.",
          {"file": FILE, "pages": PAGES, "output": OUT, "password": PWD}, ["file", "pages"], skill_extract_pages),
    Skill("rotate", "Rotate pages clockwise.",
          {"file": FILE, "degrees": {"type": "integer", "enum": [90, 180, 270]}, "pages": PAGES,
           "output": OUT, "password": PWD}, ["file", "degrees"], skill_rotate),
    Skill("extract_text", "Extract text from a PDF; optionally save to a .txt file. Does not OCR.",
          {"file": FILE, "pages": PAGES, "output": S("Optional .txt filename"), "password": PWD},
          ["file"], skill_extract_text, destructive=False),
    Skill("encrypt", "Password-protect a PDF (AES-256).",
          {"file": FILE, "user_password": S("Password required to open"),
           "owner_password": S("Optional owner password"), "output": OUT, "password": PWD},
          ["file", "user_password"], skill_encrypt),
    Skill("decrypt", "Remove password protection (requires the password).",
          {"file": FILE, "password": PWD, "output": OUT}, ["file", "password"], skill_decrypt),
    Skill("info", "Report page count, page size and metadata of a PDF.",
          {"file": FILE, "password": PWD}, ["file"], skill_info, destructive=False),
    Skill("watermark_text", "Stamp diagonal text (e.g. DRAFT, CONFIDENTIAL) on pages.",
          {"file": FILE, "text": S("Watermark text"), "pages": PAGES,
           "opacity": {"type": "number", "description": "0-1, default 0.15"}, "output": OUT, "password": PWD},
          ["file", "text"], skill_watermark_text),
    Skill("clarify", "Use ONLY when the request is ambiguous or a required value (file, password, page range) "
                     "cannot be inferred. Asks the user a question instead of guessing.",
          {"question": S("What you need to know")}, ["question"], skill_clarify, destructive=False),
]}


# --------------------------------------------------------------------------- #
# Natural language -> plan (LLM tool use)
# --------------------------------------------------------------------------- #
SYSTEM = """You route PDF requests to tools. Rules:
- Choose the fewest tool calls that fulfil the request. Use only files listed under AVAILABLE FILES.
- If steps are chained, give each intermediate an explicit output filename and reuse it as the next step's input.
- Never invent passwords, filenames or page ranges. If something required is missing, call `clarify`.
- Pages are 1-based. Copy values the user states exactly."""


def llm_plan(request: str, workdir: Path, model: str) -> list[dict]:
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic   (or pass --plan to skip the LLM)")
    files = []
    for p in sorted(workdir.glob("*.pdf")):
        try:
            files.append(f"{p.name} ({len(PdfReader(str(p)).pages)} pages)")
        except Exception:
            files.append(f"{p.name} (unreadable or encrypted)")
    tools = [{"name": s.name, "description": s.description, "input_schema": s.schema} for s in SKILLS.values()]
    resp = anthropic.Anthropic().messages.create(
        model=model, max_tokens=1024, system=SYSTEM, tools=tools, tool_choice={"type": "any"},
        messages=[{"role": "user", "content": f"AVAILABLE FILES:\n" + ("\n".join(files) or "(none)")
                   + f"\n\nREQUEST: {request}"}],
    )
    return [{"skill": b.name, "args": dict(b.input)} for b in resp.content if b.type == "tool_use"]


# --------------------------------------------------------------------------- #
# Validation, user overrides, execution
# --------------------------------------------------------------------------- #
def coerce(value: str, spec: dict):
    t = spec.get("type")
    try:
        if t == "integer":
            return int(value)
        if t == "number":
            return float(value)
        if t == "array":
            return [v.strip() for v in value.split(",") if v.strip()]
    except ValueError:
        raise SkillError(f"'{value}' is not a valid {t}")
    return value


def apply_overrides(step: dict, overrides: dict[str, str]) -> None:
    """Explicit user parameters always beat the LLM's guesses."""
    props = SKILLS[step["skill"]].properties
    for k, v in overrides.items():
        if k in props:
            step["args"][k] = coerce(v, props[k])


def validate(step: dict) -> None:
    skill = SKILLS.get(step["skill"])
    if not skill:
        raise SkillError(f"Unknown skill '{step['skill']}'")
    args = step["args"]
    unknown = set(args) - set(skill.properties)
    if unknown:
        raise SkillError(f"{skill.name}: unknown parameter(s) {sorted(unknown)}")
    missing = [r for r in skill.required if args.get(r) in (None, "", [])]
    if missing:
        raise SkillError(f"{skill.name}: missing required parameter(s) {missing}")
    for k, v in args.items():
        spec = skill.properties[k]
        if "enum" in spec and v not in spec["enum"]:
            raise SkillError(f"{skill.name}.{k} must be one of {spec['enum']}")
        if spec.get("type") == "integer" and not isinstance(v, int):
            raise SkillError(f"{skill.name}.{k} must be an integer")


def mask(args: dict) -> dict:
    return {k: ("***" if "password" in k else v) for k, v in args.items()}


def show_plan(plan: list[dict]) -> None:
    for i, s in enumerate(plan, 1):
        print(f"  {i}. {s['skill']}  {json.dumps(mask(s['args']))}")


def run(plan: list[dict], ctx: Ctx) -> int:
    for i, step in enumerate(plan, 1):
        try:
            res = SKILLS[step["skill"]].handler(ctx, step["args"])
        except SkillError as e:
            print(f"✗ step {i} ({step['skill']}): {e}")
            return 1
        except Exception as e:  # corrupt PDF, missing crypto lib, etc.
            print(f"✗ step {i} ({step['skill']}) failed: {type(e).__name__}: {e}")
            return 1
        print(f"✓ step {i}: {res['message']}")
        if step["skill"] != "clarify":
            # chained steps read from workdir; let them see earlier outputs
            for o in res["outputs"]:
                link = ctx.workdir / o
                if ctx.outdir != ctx.workdir and not link.exists():
                    link.symlink_to(ctx.outdir / o)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"pdf_agent v{VERSION}")
    ap.add_argument("request", nargs="?", help="what you want done, in plain language")
    ap.add_argument("--dir", default=".", help="working directory with input PDFs")
    ap.add_argument("--out", default=None, help="output directory (default: <dir>/output)")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                    help="explicit parameter; overrides the LLM (repeatable)")
    ap.add_argument("--plan", help="skip the LLM: JSON list of {skill, args}")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="show the plan, don't execute")
    ap.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--list-skills", action="store_true")
    ap.add_argument("--version", action="version", version=VERSION)
    a = ap.parse_args()

    if a.list_skills:
        for s in SKILLS.values():
            req = ", ".join(s.required)
            opt = ", ".join(k for k in s.properties if k not in s.required)
            print(f"{s.name:15} {s.description}\n{'':15} required: {req}   optional: {opt or '-'}")
        return 0
    if not (a.request or a.plan):
        ap.error("give a request or --plan")

    workdir = Path(a.dir).resolve()
    ctx = Ctx(workdir, Path(a.out).resolve() if a.out else workdir / "output", a.overwrite)

    try:
        overrides = dict(p.split("=", 1) for p in a.param)
    except ValueError:
        ap.error("--param must look like KEY=VALUE")

    plan = json.loads(a.plan) if a.plan else llm_plan(a.request, workdir, a.model)
    try:
        for step in plan:
            if step["skill"] not in SKILLS:
                raise SkillError(f"Unknown skill '{step['skill']}'")
            apply_overrides(step, overrides)
            validate(step)
    except SkillError as e:
        print(f"✗ {e}")
        return 1

    print("Plan:")
    show_plan(plan)
    if a.dry_run:
        return 0
    if any(SKILLS[s["skill"]].destructive for s in plan) and not a.yes:
        if input("Run? [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 1
    return run(plan, ctx)


if __name__ == "__main__":
    sys.exit(main())
