"""
skills/sandbox.py
=============================================================================
Sandboxed execution context shared by every backend (Gemini and Anthropic).

- Inputs must live inside the working directory (or the output directory,
  so chained steps can read earlier results).
- Outputs are always written into the output directory (basename only).
- Existing outputs are only replaced when `overwrite` is enabled.

While a context is active (`Ctx.run`), every file a skill writes is checked
via `claim_output`, which also records it so callers know what was produced.
=============================================================================
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .base import Skill, SkillError

_ACTIVE: ContextVar[Optional["Ctx"]] = ContextVar("pdf_sandbox", default=None)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


@dataclass
class Ctx:
    workdir: Path
    outdir: Path
    overwrite: bool = False
    strict_pages: bool = False
    written: List[Path] = field(default_factory=list)
    _step_written: Set[Path] = field(default_factory=set, repr=False)

    def __post_init__(self):
        self.workdir = Path(self.workdir).resolve()
        self.outdir = Path(self.outdir).resolve()

    def src(self, name: Union[str, Path]) -> Path:
        """Resolve an input file; must live inside workdir (or outdir, for chained steps)."""
        roots = (self.workdir, self.outdir)
        raw = Path(name)
        candidates = [raw.resolve()] if raw.is_absolute() else [(r / raw).resolve() for r in roots]
        allowed = [p for p in candidates if any(_inside(p, r) for r in roots)]
        if not allowed:
            raise SkillError(f"'{name}' is outside the working directory")
        if not raw.is_absolute() and raw.name not in ("", ".", ".."):
            # e.g. 'output/a.pdf' from a planner: look for the bare filename in the root it names
            prefix = raw.parent.parts
            named = [r for r in roots if prefix == (r.name,)]
            if prefix == ("output",) and self.outdir not in named:
                named.append(self.outdir)  # planners say 'output/' even when --out points elsewhere
            allowed += [(r / raw.name).resolve() for r in named]
        for p in allowed:
            if p.is_file():
                return p
        raise SkillError(f"File not found: {name}")

    def dst(self, name: Union[str, Path]) -> Path:
        """Resolve an output file; always written into outdir (basename only)."""
        base = Path(name).name
        if base in ("", ".", ".."):
            raise SkillError(f"Invalid output filename: '{name}'")
        p = self.outdir / base
        if p.exists() and not self.overwrite:
            raise SkillError(f"{p.name} already exists (use --overwrite)")
        self.outdir.mkdir(parents=True, exist_ok=True)
        return p

    def guard_write(self, path: Union[str, Path]) -> Path:
        p = Path(path).resolve()
        if not _inside(p, self.outdir) or p == self.outdir:
            raise SkillError(f"Refusing to write outside the output directory: {path}")
        if p.exists() and not self.overwrite and p not in self._step_written:
            raise SkillError(f"{p.name} already exists (use --overwrite)")
        self._step_written.add(p)
        if p not in self.written:
            self.written.append(p)
        return p

    @contextmanager
    def activate(self):
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)

    def run(self, skill: Skill, params: Dict[str, Any]) -> Tuple[Any, List[Path]]:
        """Resolve a skill's path parameters through the sandbox and execute it.

        :return: (skill result, list of files written by this step)
        """
        args = dict(params)
        for key in skill.input_params:
            value = args.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, (list, tuple)):
                args[key] = [str(self.src(v)) for v in value]
            else:
                args[key] = str(self.src(value))
        for key in skill.output_params:
            value = args.get(key)
            if value not in (None, ""):
                args[key] = str(self.dst(value))

        start = len(self.written)
        self._step_written = set()
        with self.activate():
            result = skill.execute(**args)
        return result, self.written[start:]


def strict_pages() -> bool:
    """Whether the active sandbox wants strict page parsing (keep order/duplicates, reject out-of-range)."""
    ctx = _ACTIVE.get()
    return bool(ctx and ctx.strict_pages)


def claim_output(path: Union[str, Path]) -> str:
    """Called by skills before writing a file: enforces the active sandbox (if any)
    and makes sure the parent directory exists."""
    ctx = _ACTIVE.get()
    if ctx is not None:
        ctx.guard_write(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def mask_secrets(args: Dict[str, Any]) -> Dict[str, Any]:
    """Hides password values when printing parameters."""
    return {k: ("***" if "password" in k and v else v) for k, v in args.items()}
