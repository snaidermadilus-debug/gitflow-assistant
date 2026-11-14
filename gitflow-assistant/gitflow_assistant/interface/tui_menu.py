"""Interactive text menu. Every option runs the same handlers as the CLI."""

from __future__ import annotations

import shlex
from typing import Callable, List, Optional

from gitflow_assistant import __version__
from gitflow_assistant.core.project_detector import detect_project
from gitflow_assistant.i18n import t
from gitflow_assistant.interface.cli_parser import build_parser
from gitflow_assistant.interface.prompts import ConsoleUI
from gitflow_assistant.interface.runner import execute
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.errors import Cancelled, UsageError


class Menu:
    """Main menu loop."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        assert isinstance(ctx.ui, ConsoleUI)
        self.ui: ConsoleUI = ctx.ui
        self.parser = build_parser()

    # ------------------------------------------------------------ helpers
    def run(self, argv: List[str]) -> int:
        """Parse ``argv`` exactly like the CLI and execute it."""
        try:
            args = self.parser.parse_args(argv)
        except SystemExit:
            return 2
        return execute(self.ctx, args)

    def sub(self, title: str, entries: List[tuple]) -> None:
        """Generic sub-menu: entries are (label, callable returning argv or None)."""
        labels = [label for label, _ in entries] + [t("menu.back")]
        choice = self.ui.choose(title, labels, 0)
        if choice == len(entries):
            return
        builder: Callable[[], Optional[List[str]]] = entries[choice][1]
        argv = builder()
        if argv:
            self.run(argv)

    def header(self) -> None:
        self.ui.heading(f"GITFLOW ASSISTANT {__version__} — {t('menu.subtitle')}")
        path = self.ctx.project_path()
        if path:
            info = detect_project(path)
            branch = f" [{info.branch}]" if info.branch else ""
            self.ui.info(t("menu.current", name=info.name, branch=branch, state=t(f"state.{info.state}"),
                           pending=info.pending, path=str(info.path)))
        else:
            self.ui.warning(t("menu.no_project"))

    # ----------------------------------------------------------- options
    def projects(self) -> None:
        self.sub(t("menu.projects"), [
            (t("menu.p_list"), lambda: ["projects", "list"]),
            (t("menu.p_select"), lambda: ["select"]),
            (t("menu.p_add"), lambda: ["projects", "add", self.ui.ask(t("select.path"))]),
            (t("menu.p_scan"), lambda: ["projects", "scan", "--add"] + shlex.split(self.ui.ask(t("menu.p_scan_dirs"), ""))),
            (t("menu.p_status"), lambda: ["status"]),
            (t("menu.p_init"), lambda: ["init"]),
            (t("menu.p_remove"), lambda: ["projects", "remove", self.ui.ask(t("select.path"))]),
        ])

    def clone(self) -> Optional[List[str]]:
        url = self.ui.ask(t("menu.clone_url"))
        if not url:
            return None
        dest = self.ui.ask(t("menu.clone_dest"), "")
        return ["clone", url] + ([dest] if dest else [])

    def create_repo(self) -> Optional[List[str]]:
        name = self.ui.ask(t("github.repo_name"))
        if not name:
            return None
        private = self.ui.choose(t("github.visibility"), [t("github.public"), t("github.private")], 0) == 1
        desc = self.ui.ask(t("github.description"), "")
        argv = ["github", "create", name, "--private" if private else "--public", "--description", desc]
        if self.ctx.project_path() and self.ui.confirm(t("menu.set_remote_question"), True):
            argv.append("--set-remote")
        return argv

    def branches(self) -> None:
        self.sub(t("menu.branches"), [
            (t("menu.b_list"), lambda: ["branch", "list"]),
            (t("menu.b_create"), lambda: ["branch", "create", self.ui.ask(t("menu.b_name")), "--switch"]),
            (t("menu.b_switch"), lambda: ["branch", "switch", self.ui.ask(t("menu.b_name"))]),
            (t("menu.b_rename"), lambda: ["branch", "rename", self.ui.ask(t("menu.b_name"))]),
            (t("menu.b_delete"), lambda: ["branch", "delete", self.ui.ask(t("menu.b_name"))]),
        ])

    def history(self) -> None:
        self.sub(t("menu.history"), [
            (t("menu.h_log"), lambda: ["history", "log", "-n", "30"]),
            (t("menu.h_ops"), lambda: ["history", "ops"]),
            (t("menu.h_pub"), lambda: ["history", "publications"]),
            (t("menu.h_backup"), lambda: ["backup", "create"]),
            (t("menu.h_backups"), lambda: ["backup", "list"]),
            (t("menu.h_commit"), lambda: ["commit"]),
            (t("menu.h_push"), lambda: ["push"]),
            (t("menu.h_pull"), lambda: ["pull"]),
        ])

    def diff(self) -> None:
        self.sub(t("menu.diff"), [
            (t("menu.d_work"), lambda: ["diff"]),
            (t("menu.d_staged"), lambda: ["diff", "--staged"]),
            (t("menu.d_stat"), lambda: ["diff", "--stat"]),
            (t("menu.d_refs"), lambda: ["diff", self.ui.ask(t("menu.d_ref_a"), "HEAD~1"), self.ui.ask(t("menu.d_ref_b"), "HEAD")]),
        ])

    def security(self) -> None:
        self.sub(t("menu.security"), [
            (t("menu.s_project"), lambda: ["scan", "--show-ignored"]),
            (t("menu.s_staged"), lambda: ["scan", "--staged"]),
            (t("menu.s_github"), lambda: ["github", "status"]),
            (t("menu.s_login"), lambda: ["github", "login"]),
        ])

    def settings(self) -> None:
        self.sub(t("menu.settings"), [
            (t("menu.c_show"), lambda: ["config", "show"]),
            (t("menu.c_set"), lambda: ["config", "set", self.ui.ask(t("menu.c_key")), self.ui.ask(t("menu.c_value"))]),
            (t("menu.c_lang"), lambda: ["config", "set", "language",
                                        ["pt", "en", "es"][self.ui.choose(t("menu.c_lang"), ["Português", "English", "Español"], 0)]]),
            (t("menu.c_aliases"), lambda: ["config", "alias"]),
            (t("menu.c_path"), lambda: ["config", "path"]),
        ])

    def ai(self) -> None:
        self.sub(t("menu.ai"), [
            (t("menu.a_status"), lambda: ["ai", "status"]),
            (t("menu.a_summary"), lambda: ["ai", "summary"]),
            (t("menu.a_summary_staged"), lambda: ["ai", "summary", "--staged"]),
            (t("menu.a_commit"), lambda: ["commit", "--ai"]),
            (t("menu.a_login"), lambda: ["ai", "login"]),
            (t("menu.a_models"), lambda: ["ai", "models"]),
        ])

    # --------------------------------------------------------------- loop
    def loop(self) -> int:
        actions: List[tuple] = [
            (t("menu.1"), self.projects),
            (t("menu.2"), lambda: self.run(["upload"])),
            (t("menu.3"), lambda: self.run(["update"])),
            (t("menu.4"), lambda: (lambda a: self.run(a) if a else None)(self.clone())),
            (t("menu.5"), lambda: (lambda a: self.run(a) if a else None)(self.create_repo())),
            (t("menu.6"), self.branches),
            (t("menu.7"), self.history),
            (t("menu.8"), self.diff),
            (t("menu.9"), self.security),
            (t("menu.10"), lambda: self.run(["readme"])),
            (t("menu.11"), lambda: self.run(["gitignore"])),
            (t("menu.12"), lambda: self.run(["doctor"])),
            (t("menu.13"), self.settings),
            (t("menu.14"), self.ai),
        ]
        while True:
            self.header()
            for number, (label, _) in enumerate(actions, start=1):
                self.ui.out.print(f"  [{number:>2}] {label}")
            self.ui.out.print(f"  [ 0] {t('menu.exit')}")
            answer = self.ui.ask(t("menu.prompt"), "").strip()
            if answer in ("0", "q", "quit", "exit", "sair", "salir"):
                return 0
            if answer in ("h", "?", "help", "ajuda", "ayuda"):
                self.ui.text_block(self.parser.format_help())
                continue
            if not answer.isdigit() or not 1 <= int(answer) <= len(actions):
                self.ui.warning(t("prompt.invalid"))
                continue
            try:
                actions[int(answer) - 1][1]()
            except (Cancelled, UsageError) as exc:
                self.ui.warning(str(exc))
            except KeyboardInterrupt:
                self.ui.out.print("")
                self.ui.warning(t("common.cancelled"))
            if self.ui.interactive:
                self.ui.ask(t("menu.continue"), "")


def run_menu(ctx: AppContext) -> int:
    """Start the interactive menu (requires an interactive terminal)."""
    if not ctx.ui.interactive:
        ctx.ui.error(t("menu.needs_tty"))
        return 2
    return Menu(ctx).loop()
