"""Terminal output with Rich when available and a plain-text fallback.

Messages go to stderr when ``--json`` is active so stdout carries only JSON.
"""

from __future__ import annotations

import contextlib
import json
import sys
from typing import Any, Iterator, Optional, Sequence, TextIO

try:  # optional dependency
    from rich.console import Console
    from rich.syntax import Syntax
    from rich.table import Table

    HAVE_RICH = True
except ImportError:  # pragma: no cover - exercised on minimal installs
    HAVE_RICH = False


def _stream_supports_unicode(stream: TextIO) -> bool:
    encoding = (getattr(stream, "encoding", None) or "").lower()
    return "utf" in encoding


class Output:
    """Render messages, tables and progress indicators."""

    def __init__(self, color: bool = True, json_mode: bool = False, stream: Optional[TextIO] = None,
                 err_stream: Optional[TextIO] = None) -> None:
        self.json_mode = json_mode
        self.stream = stream or sys.stdout
        self.err_stream = err_stream or sys.stderr
        self.msg_stream = self.err_stream if json_mode else self.stream
        self.use_rich = bool(color and HAVE_RICH)
        self.unicode = _stream_supports_unicode(self.msg_stream)
        if self.use_rich:
            self.console = Console(file=self.msg_stream, highlight=False, soft_wrap=False)
            self.err_console = Console(file=self.err_stream, highlight=False)

    # ---------------------------------------------------------- messages
    def _plain(self, prefix: str, message: str, stream: Optional[TextIO] = None) -> None:
        print(f"{prefix} {message}" if prefix else message, file=stream or self.msg_stream, flush=True)

    def print(self, message: str = "") -> None:
        if self.use_rich:
            self.console.print(message, markup=False)
        else:
            self._plain("", message)

    def info(self, message: str) -> None:
        if self.use_rich:
            self.console.print(f"[cyan]i[/cyan] {_escape(message)}")
        else:
            self._plain("[i]", message)

    def success(self, message: str) -> None:
        if self.use_rich:
            self.console.print(f"[bold green]{'✔' if self.unicode else 'OK'}[/bold green] {_escape(message)}")
        else:
            self._plain("[OK]", message)

    def warning(self, message: str) -> None:
        if self.use_rich:
            self.console.print(f"[bold yellow]![/bold yellow] [yellow]{_escape(message)}[/yellow]")
        else:
            self._plain("[!]", message)

    def error(self, message: str) -> None:
        if self.use_rich:
            self.err_console.print(f"[bold red]{'✖' if self.unicode else 'X'}[/bold red] [red]{_escape(message)}[/red]")
        else:
            self._plain("[x]", message, self.err_stream)

    def heading(self, message: str) -> None:
        if self.use_rich:
            self.console.rule(f"[bold]{_escape(message)}[/bold]", style="blue")
        else:
            self._plain("", f"\n== {message} ==")

    def table(self, title: str, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        if not rows:
            return
        if self.use_rich:
            table = Table(title=title or None, title_justify="left", header_style="bold blue", show_lines=False)
            for header in headers:
                table.add_column(header, overflow="fold")
            for row in rows:
                table.add_row(*[_escape(str(c)) for c in row])
            self.console.print(table)
            return
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
        widths = [min(w, 60) for w in widths]
        if title:
            self._plain("", title)
        self._plain("", "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)))
        self._plain("", "  ".join("-" * w for w in widths))
        for row in rows:
            self._plain("", "  ".join(str(c)[:60].ljust(widths[i]) for i, c in enumerate(row)))

    def text_block(self, text: str, syntax: str = "") -> None:
        if self.use_rich and syntax:
            self.console.print(Syntax(text, syntax, theme="ansi_dark", word_wrap=True))
        else:
            print(text, file=self.msg_stream, flush=True)

    @contextlib.contextmanager
    def progress(self, message: str) -> Iterator[None]:
        """Spinner (Rich) or a single status line (plain)."""
        if self.use_rich and self.console.is_terminal:
            with self.console.status(_escape(message), spinner="dots"):
                yield
        else:
            self._plain("...", message)
            yield

    def emit_json(self, data: Any) -> None:
        """Write machine-readable JSON to stdout."""
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str), file=self.stream, flush=True)


def _escape(text: str) -> str:
    """Escape Rich markup in user-provided text."""
    return text.replace("[", r"\[")
