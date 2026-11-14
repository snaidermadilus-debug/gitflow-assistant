"""Pre-publication security scanner.

Classifies each file as one of:

* ``ignored``        – excluded by ``.gitignore`` or user exclusion rules;
* ``suspicious``     – heuristic match that needs human review;
* ``secret``         – high-confidence secret (blocked by default);
* ``false_positive`` – previously reviewed and dismissed by the user;
* ``allowed``        – explicitly allowed by the user's allow patterns.

Content is read in a streaming fashion and limited to a configurable size;
binary files are only checked by name and size.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.security.secret_detector import (
    CONFIRMED,
    SUSPICIOUS,
    check_name,
    fingerprint,
    matches_any,
    scan_lines,
)

IGNORED = "ignored"
FALSE_POSITIVE = "false_positive"
ALLOWED = "allowed"
LARGE = "large"
SEVERITY = {CONFIRMED: 3, SUSPICIOUS: 2, LARGE: 2, FALSE_POSITIVE: 0, ALLOWED: 0, IGNORED: 0}
DISCLAIMER = ("Heuristic analysis: a clean result does not guarantee the absence of secrets, "
              "and findings may be false positives.")


@dataclass
class Finding:
    """One security observation about a file."""

    path: str
    category: str
    rule: str
    description: str
    line: int = 0
    excerpt: str = ""
    fingerprint: str = ""

    @property
    def blocking(self) -> bool:
        return self.category == CONFIRMED

    @property
    def needs_review(self) -> bool:
        return self.category in (CONFIRMED, SUSPICIOUS, LARGE)


@dataclass
class ScanReport:
    """Aggregated findings."""

    scanned: int = 0
    findings: List[Finding] = field(default_factory=list)
    skipped_binary: List[str] = field(default_factory=list)
    truncated: List[str] = field(default_factory=list)

    def by_category(self, category: str) -> List[Finding]:
        return [f for f in self.findings if f.category == category]

    @property
    def secrets(self) -> List[Finding]:
        return self.by_category(CONFIRMED)

    @property
    def review_needed(self) -> List[Finding]:
        return [f for f in self.findings if f.needs_review]

    @property
    def flagged_paths(self) -> List[str]:
        return sorted({f.path for f in self.review_needed})

    @property
    def is_clean(self) -> bool:
        return not self.review_needed


class SecurityScanner:
    """Scan working-tree or staged files before publication."""

    def __init__(self, max_file_size_mb: int = 50, max_content_kb: int = 1024,
                 exclude_patterns: Sequence[str] = (), allow_patterns: Sequence[str] = (),
                 false_positives: Sequence[str] = ()) -> None:
        self.max_file_size = int(max_file_size_mb) * 1024 * 1024
        self.max_content = int(max_content_kb) * 1024
        self.exclude_patterns = list(exclude_patterns)
        self.allow_patterns = list(allow_patterns)
        self.false_positives = set(false_positives)

    # ------------------------------------------------------------ helpers
    def _classify(self, path: str, rule: str, level: str, description: str, line: int = 0,
                  excerpt: str = "", fp: str = "") -> Finding:
        fp = fp or fingerprint(path, rule, "")
        if matches_any(path, self.allow_patterns):
            category = ALLOWED
        elif fp in self.false_positives:
            category = FALSE_POSITIVE
        else:
            category = level
        return Finding(path, category, rule, description, line, excerpt, fp)

    def _scan_stream(self, path: str, stream: io.BufferedIOBase, size: int, report: ScanReport) -> None:
        head = stream.read(8192)
        if b"\x00" in head:
            report.skipped_binary.append(path)
            return
        if size > self.max_content:
            report.truncated.append(path)

        def lines() -> Iterable[str]:
            remaining = self.max_content - len(head)
            buffer = head
            while True:
                text = buffer.decode("utf-8", errors="replace")
                parts = text.split("\n")
                # keep the incomplete last line for the next chunk
                for part in parts[:-1]:
                    yield part
                tail = parts[-1].encode("utf-8")
                if remaining <= 0:
                    if tail:
                        yield tail.decode("utf-8", errors="replace")
                    return
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    if tail:
                        yield tail.decode("utf-8", errors="replace")
                    return
                remaining -= len(chunk)
                buffer = tail + chunk

        for match in scan_lines(path, lines()):
            report.findings.append(self._classify(path, match.rule_id, match.level, match.description,
                                                  match.line, match.excerpt, match.fingerprint))

    def _check_meta(self, path: str, size: int, report: ScanReport) -> None:
        name_rule = check_name(path)
        if name_rule:
            glob, level, description = name_rule
            report.findings.append(self._classify(path, f"name:{glob}", level, description))
        if size > self.max_file_size:
            report.findings.append(self._classify(path, "large-file", LARGE,
                                                  f"file larger than {self.max_file_size // (1024 * 1024)} MB "
                                                  f"({size / (1024 * 1024):.1f} MB)"))

    # ------------------------------------------------------------- public
    def scan_files(self, root: Path, paths: Sequence[str], engine: Optional[GitEngine] = None) -> ScanReport:
        """Scan working-tree files (relative to ``root``)."""
        report = ScanReport()
        ignored = set(engine.check_ignore(list(paths))) if engine and paths else set()
        for rel in paths:
            if rel in ignored or matches_any(rel, self.exclude_patterns):
                report.findings.append(Finding(rel, IGNORED, "ignore", "excluded by .gitignore or exclusion rules"))
                continue
            full = root / rel
            if not full.is_file():
                continue
            report.scanned += 1
            size = full.stat().st_size
            self._check_meta(rel, size, report)
            try:
                with full.open("rb") as handle:
                    self._scan_stream(rel, handle, size, report)  # type: ignore[arg-type]
            except OSError as exc:
                report.findings.append(Finding(rel, SUSPICIOUS, "unreadable", f"cannot read file: {exc}"))
        return report

    def scan_staged(self, engine: GitEngine) -> ScanReport:
        """Scan the *staged* content – exactly what the next commit will contain."""
        report = ScanReport()
        for rel in engine.staged_files():
            report.scanned += 1
            size = engine.staged_size(rel)
            self._check_meta(rel, size, report)
            data = engine.staged_blob(rel, self.max_content + 8192)
            self._scan_stream(rel, io.BytesIO(data), size, report)  # type: ignore[arg-type]
        return report

    def scan_project(self, engine: GitEngine) -> ScanReport:
        """Scan every tracked and untracked (non-ignored) file of a repository."""
        root = engine.root() or engine.cwd
        res = engine.run(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], check=True)
        paths = sorted({p for p in res.stdout.split("\x00") if p})
        report = self.scan_files(root, paths, engine=None)
        ignored = engine.run(["ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"])
        for rel in [p for p in ignored.stdout.split("\x00") if p][:200]:
            report.findings.append(Finding(rel, IGNORED, "gitignore", "ignored by .gitignore (will not be sent)"))
        return report
