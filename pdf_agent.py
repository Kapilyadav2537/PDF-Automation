#!/usr/bin/env python3
"""
pdf_agent v1 - natural language -> PDF skill activation with user-provided parameters.

Uses Anthropic Claude for tool calling over the shared skill registry in `skills/`
(the same skills the Gemini CLI in `main.py` uses).

Flow:  request  ->  LLM picks skill(s) + args (tool use)  ->  merge with your
       explicit --param overrides  ->  validate  ->  show plan  ->  confirm  ->  run

Examples:
  export ANTHROPIC_API_KEY=...
  python pdf_agent.py "merge report.pdf and appendix.pdf into final.pdf"
  python pdf_agent.py "rotate the first 3 pages of scan.pdf by 90" --dry-run
  python pdf_agent.py "split book.pdf" --param pages_per_file=10 --yes
  python pdf_agent.py --list-skills
  python pdf_agent.py --plan '[{"skill":"pdf_info","args":{"input_pdf_path":"a.pdf"}}]'   # no LLM

Requires: pip install -r requirements.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pypdf import PdfReader

from skills import Ctx, SkillError, mask_secrets, registry

VERSION = "1.0.0"
DEFAULT_MODEL = os.environ.get("PDF_AGENT_MODEL", "claude-sonnet-5-5")
MAX_PRINTED_RESULT = 4000


# --------------------------------------------------------------------------- #
# Natural language -> plan (LLM tool use over the shared skill registry)
# --------------------------------------------------------------------------- #
SYSTEM = """You route PDF requests to tools. Rules:
- Choose the fewest tool calls that fulfil the request. Use only files listed under AVAILABLE FILES.
- Pass input files by filename exactly as listed; output paths are plain filenames (written to the output folder).
- If steps are chained, give each intermediate an explicit output filename and reuse it as the next step's input.
- Never invent passwords, filenames or page ranges. If something required is missing, call `clarify`.
- Pages are 1-based. Copy values the user states exactly."""


def anthropic_tools() -> list[dict]:
    return [{"name": s.name, "description": s.description, "input_schema": s.parameters_schema}
            for s in registry.list_skills()]


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
    resp = anthropic.Anthropic().messages.create(
        model=model, max_tokens=1024, system=SYSTEM, tools=anthropic_tools(), tool_choice={"type": "any"},
        messages=[{"role": "user", "content": f"AVAILABLE FILES:\n" + ("\n".join(files) or "(none)")
                   + f"\n\nREQUEST: {request}"}],
    )
    return [{"skill": b.name, "args": dict(b.input)} for b in resp.content if b.type == "tool_use"]


# --------------------------------------------------------------------------- #
# Validation, user overrides, execution
# --------------------------------------------------------------------------- #
def coerce(value: str, spec: dict):
    options = spec.get("anyOf", [spec])
    if any(o.get("type", "string") == "string" for o in options):
        return value
    t = options[0].get("type")
    try:
        if t == "integer":
            return int(value)
        if t == "number":
            return float(value)
        if t == "array":
            items = [v.strip() for v in value.split(",") if v.strip()]
            return [int(v) for v in items] if options[0].get("items", {}).get("type") == "integer" else items
    except ValueError:
        raise SkillError(f"'{value}' is not a valid {t}")
    return value


def apply_overrides(step: dict, overrides: dict[str, str]) -> None:
    """Explicit user parameters always beat the LLM's guesses."""
    props = registry.get_skill(step["skill"]).properties
    for k, v in overrides.items():
        if k in props:
            step["args"][k] = coerce(v, props[k])


def validate(step: dict) -> None:
    skill = registry.get_skill(step["skill"])
    if not skill:
        raise SkillError(f"Unknown skill '{step['skill']}'")
    skill.validate(step["args"])


def show_plan(plan: list[dict]) -> None:
    for i, s in enumerate(plan, 1):
        print(f"  {i}. {s['skill']}  {json.dumps(mask_secrets(s['args']))}")


def run(plan: list[dict], ctx: Ctx) -> int:
    for i, step in enumerate(plan, 1):
        try:
            result, _ = ctx.run(registry.get_skill(step["skill"]), step["args"])
        except (SkillError, FileNotFoundError) as e:
            print(f"✗ step {i} ({step['skill']}): {e}")
            return 1
        except Exception as e:  # corrupt PDF, missing crypto lib, etc.
            print(f"✗ step {i} ({step['skill']}) failed: {type(e).__name__}: {e}")
            return 1
        text = str(result)
        if len(text) > MAX_PRINTED_RESULT:
            text = text[:MAX_PRINTED_RESULT] + "\n...[truncated]"
        print(f"✓ step {i}: {text}")
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
        for s in registry.list_skills():
            req = ", ".join(s.required)
            opt = ", ".join(k for k in s.properties if k not in s.required)
            print(f"{s.name:22} {s.description}\n{'':22} required: {req or '-'}   optional: {opt or '-'}")
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
            if not registry.get_skill(step["skill"]):
                raise SkillError(f"Unknown skill '{step['skill']}'")
            step.setdefault("args", {})
            apply_overrides(step, overrides)
            validate(step)
    except SkillError as e:
        print(f"✗ {e}")
        return 1

    print("Plan:")
    show_plan(plan)
    if a.dry_run:
        return 0
    if any(registry.get_skill(s["skill"]).destructive for s in plan) and not a.yes:
        if input("Run? [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 1
    return run(plan, ctx)


if __name__ == "__main__":
    sys.exit(main())
