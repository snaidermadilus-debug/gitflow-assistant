"""Application bootstrap: build the context and dispatch to the CLI or the TUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from gitflow_assistant import i18n
from gitflow_assistant.core.configuration import Configuration
from gitflow_assistant.core.repository_manager import RepositoryManager
from gitflow_assistant.interface.cli_parser import build_parser, expand_aliases, hoist_global_options
from gitflow_assistant.interface.logger import setup_logging
from gitflow_assistant.interface.output import Output
from gitflow_assistant.interface.prompts import ConsoleUI
from gitflow_assistant.interface.runner import EXIT_INTERRUPT, execute
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.history_service import OperationHistory
from gitflow_assistant.utils.os_detector import detect_platform


def _configure_stdio() -> None:
    """Use UTF-8 on Windows consoles and replace unencodable characters everywhere."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                continue


def _pre_language(argv: Sequence[str]) -> Optional[str]:
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def build_context(args, config: Configuration) -> AppContext:  # type: ignore[no-untyped-def]
    """Create the shared context from parsed global options."""
    plat = detect_platform()
    theme = str(config.get("theme", "auto"))
    color = not args.no_color and theme != "plain" and not os.environ.get("NO_COLOR")
    out = Output(color=color, json_mode=args.json)
    interactive = plat.interactive and not args.non_interactive and not args.json
    ui = ConsoleUI(out, interactive=interactive, mode=str(config.get("confirm.mode", "risky")),
                   assume_yes=args.yes, allow_risky=args.allow_risky)
    return AppContext(config=config, ui=ui, repos=RepositoryManager(),
                      history=OperationHistory(max_entries=int(config.get("history.max_entries", 1000))),
                      project_override=Path(args.project).expanduser() if args.project else None)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point of the ``gitflow`` executable."""
    _configure_stdio()
    raw = list(sys.argv[1:] if argv is None else argv)
    config = Configuration()
    i18n.set_language(_pre_language(raw) or str(config.get("language", "auto")))
    raw = expand_aliases(hoist_global_options(raw), config.get("aliases") or {})
    parser = build_parser()
    args = parser.parse_args(raw)
    setup_logging(args.verbose)
    ctx = build_context(args, config)
    if config.load_error:
        ctx.ui.warning(config.load_error)
    if not args.command:
        args.command = "menu"
    try:
        return execute(ctx, args)
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        ctx.ui.warning(i18n.t("common.interrupted"))
        return EXIT_INTERRUPT


if __name__ == "__main__":
    sys.exit(main())
