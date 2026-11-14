"""Command-line parser for ``gitflow``."""

from __future__ import annotations

import argparse
from typing import List, Mapping, Sequence

from gitflow_assistant import __version__
from gitflow_assistant.i18n import t

STRATEGIES = ("ff-only", "merge", "rebase")
COMMANDS = ("init", "status", "projects", "select", "upload", "update", "clone", "commit", "push", "pull", "abort",
            "branch", "history", "diff", "scan", "doctor", "config", "remote", "github", "gitignore", "readme",
            "backup", "untrack", "ai", "menu")


def _selection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-m", "--message", help=t("help.message"))
    p.add_argument("--all", action="store_true", dest="all_files", help=t("help.all"))
    p.add_argument("--files", nargs="+", metavar="PATH", help=t("help.files"))
    p.add_argument("--accept-findings", action="store_true", help=t("help.accept_findings"))
    p.add_argument("--ai", action="store_true", help=t("help.ai_flag"))


def build_parser() -> argparse.ArgumentParser:
    """Create the complete argument parser."""
    parser = argparse.ArgumentParser(prog="gitflow", description=t("help.description"),
                                     epilog=t("help.epilog"), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-V", "--version", action="version", version=f"GitFlow Assistant {__version__}")
    parser.add_argument("-C", "--project", metavar="PATH", help=t("help.project"))
    parser.add_argument("-y", "--yes", action="store_true", help=t("help.yes"))
    parser.add_argument("--allow-risky", action="store_true", help=t("help.allow_risky"))
    parser.add_argument("--non-interactive", "--batch", action="store_true", help=t("help.non_interactive"))
    parser.add_argument("--json", action="store_true", help=t("help.json"))
    parser.add_argument("--lang", choices=("pt", "en", "es"), help=t("help.lang"))
    parser.add_argument("--no-color", action="store_true", help=t("help.no_color"))
    parser.add_argument("-v", "--verbose", action="store_true", help=t("help.verbose"))
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("init", help=t("help.init"))
    p.add_argument("path", nargs="?", default=None)
    p.add_argument("--branch", help=t("help.branch_name"))
    p.add_argument("--gitignore", action="store_true", help=t("help.init_gitignore"))

    p = sub.add_parser("status", help=t("help.status"))
    p.add_argument("--fetch", action="store_true", help=t("help.fetch"))

    p = sub.add_parser("projects", help=t("help.projects"))
    ps = p.add_subparsers(dest="action")
    ps.add_parser("list", help=t("help.projects_list"))
    a = ps.add_parser("add", help=t("help.projects_add"))
    a.add_argument("path")
    a = ps.add_parser("remove", help=t("help.projects_remove"))
    a.add_argument("path")
    a = ps.add_parser("scan", help=t("help.projects_scan"))
    a.add_argument("dirs", nargs="*")
    a.add_argument("--depth", type=int, default=None)
    a.add_argument("--add", action="store_true", help=t("help.projects_scan_add"))
    ps.add_parser("prune", help=t("help.projects_prune"))

    p = sub.add_parser("select", help=t("help.select"))
    p.add_argument("path", nargs="?")

    p = sub.add_parser("upload", aliases=["publish"], help=t("help.upload"))
    p.add_argument("path", nargs="?")
    _selection_args(p)
    p.add_argument("--remote", dest="remote_url", metavar="URL", help=t("help.remote_url"))
    p.add_argument("--create-github", action="store_true", help=t("help.create_github"))
    p.add_argument("--name", dest="repo_name", help=t("help.repo_name"))
    vis = p.add_mutually_exclusive_group()
    vis.add_argument("--private", dest="private", action="store_true", default=None)
    vis.add_argument("--public", dest="private", action="store_false")
    p.add_argument("--description", default="")
    p.add_argument("--ssh", action="store_true", help=t("help.ssh"))
    p.add_argument("--no-push", action="store_true", help=t("help.no_push"))

    p = sub.add_parser("update", aliases=["sync"], help=t("help.update"))
    _selection_args(p)
    p.add_argument("--strategy", choices=STRATEGIES, help=t("help.strategy"))
    p.add_argument("--no-push", action="store_true", help=t("help.no_push"))

    p = sub.add_parser("clone", help=t("help.clone"))
    p.add_argument("url")
    p.add_argument("destination", nargs="?")
    p.add_argument("--branch")
    p.add_argument("--depth", type=int)

    p = sub.add_parser("commit", help=t("help.commit"))
    _selection_args(p)
    p.add_argument("--type", dest="kind", help=t("help.commit_type"))
    p.add_argument("--scope", default="")

    sub.add_parser("push", help=t("help.push"))
    p = sub.add_parser("pull", help=t("help.pull"))
    p.add_argument("--strategy", choices=STRATEGIES, default=None, help=t("help.strategy"))
    sub.add_parser("abort", help=t("help.abort"))

    p = sub.add_parser("branch", help=t("help.branch"))
    bs = p.add_subparsers(dest="action")
    bs.add_parser("list")
    a = bs.add_parser("create")
    a.add_argument("name")
    a.add_argument("--from", dest="start_point")
    a.add_argument("--switch", action="store_true")
    a = bs.add_parser("switch")
    a.add_argument("name")
    mode = a.add_mutually_exclusive_group()
    mode.add_argument("--stash", dest="stash", action="store_true", default=None, help=t("help.stash"))
    mode.add_argument("--carry", dest="stash", action="store_false", help=t("help.carry"))
    a = bs.add_parser("delete")
    a.add_argument("name")
    a = bs.add_parser("rename")
    a.add_argument("new_name")

    p = sub.add_parser("history", aliases=["log"], help=t("help.history"))
    hs = p.add_subparsers(dest="action")
    a = hs.add_parser("log")
    a.add_argument("-n", "--limit", type=int, default=20)
    a.add_argument("--file")
    a.add_argument("--ref")
    a = hs.add_parser("ops")
    a.add_argument("-n", "--limit", type=int, default=30)
    a = hs.add_parser("publications")
    a.add_argument("-n", "--limit", type=int, default=30)
    p.add_argument("-n", "--limit", type=int, default=20)

    p = sub.add_parser("diff", help=t("help.diff"))
    p.add_argument("refs", nargs="*", metavar="REF")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--stat", action="store_true")
    p.add_argument("--files", nargs="+")

    p = sub.add_parser("scan", help=t("help.scan"))
    p.add_argument("--staged", action="store_true", help=t("help.scan_staged"))
    p.add_argument("--mark-false-positive", nargs="+", metavar="FINGERPRINT", help=t("help.mark_fp"))
    p.add_argument("--show-ignored", action="store_true")

    p = sub.add_parser("doctor", help=t("help.doctor"))
    p.add_argument("--offline", action="store_true", help=t("help.offline"))

    p = sub.add_parser("config", help=t("help.config"))
    cs = p.add_subparsers(dest="action")
    cs.add_parser("show")
    cs.add_parser("path")
    a = cs.add_parser("get")
    a.add_argument("key")
    a = cs.add_parser("set")
    a.add_argument("key")
    a.add_argument("value")
    a = cs.add_parser("unset")
    a.add_argument("key")
    cs.add_parser("reset")
    a = cs.add_parser("export")
    a.add_argument("file")
    a = cs.add_parser("import")
    a.add_argument("file")
    a = cs.add_parser("alias")
    a.add_argument("name", nargs="?")
    a.add_argument("target", nargs=argparse.REMAINDER)
    a = cs.add_parser("unalias")
    a.add_argument("name")

    p = sub.add_parser("remote", help=t("help.remote"))
    rs = p.add_subparsers(dest="action")
    rs.add_parser("list")
    a = rs.add_parser("set")
    a.add_argument("name")
    a.add_argument("url")
    a = rs.add_parser("remove")
    a.add_argument("name")

    p = sub.add_parser("github", aliases=["gh"], help=t("help.github"))
    gs = p.add_subparsers(dest="action")
    gs.add_parser("status")
    a = gs.add_parser("login")
    a.add_argument("--device", action="store_true", help=t("help.device"))
    a.add_argument("--token-stdin", action="store_true", help=t("help.token_stdin"))
    a.add_argument("--store", action="store_true", help=t("help.store"))
    gs.add_parser("logout")
    a = gs.add_parser("repos")
    a.add_argument("-n", "--limit", type=int, default=30)
    a = gs.add_parser("create")
    a.add_argument("name")
    vis = a.add_mutually_exclusive_group()
    vis.add_argument("--private", dest="private", action="store_true", default=None)
    vis.add_argument("--public", dest="private", action="store_false")
    a.add_argument("--description", default="")
    a.add_argument("--set-remote", action="store_true")
    a.add_argument("--ssh", action="store_true")
    a = gs.add_parser("info")
    a.add_argument("repo", nargs="?", metavar="OWNER/REPO")
    a = gs.add_parser("describe")
    a.add_argument("text")
    a = gs.add_parser("branches")
    a.add_argument("repo", nargs="?", metavar="OWNER/REPO")
    a = gs.add_parser("commits")
    a.add_argument("repo", nargs="?", metavar="OWNER/REPO")
    a.add_argument("-n", "--limit", type=int, default=10)

    p = sub.add_parser("gitignore", help=t("help.gitignore"))
    p.add_argument("--print", dest="print_only", action="store_true")
    p.add_argument("--language", nargs="+", dest="languages")

    p = sub.add_parser("readme", help=t("help.readme"))
    p.add_argument("--description", default="")
    p.add_argument("--print", dest="print_only", action="store_true")
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("backup", help=t("help.backup"))
    bk = p.add_subparsers(dest="action")
    bk.add_parser("create")
    bk.add_parser("list")

    p = sub.add_parser("untrack", help=t("help.untrack"))
    p.add_argument("paths", nargs="+")
    p.add_argument("--delete", action="store_true", help=t("help.untrack_delete"))

    p = sub.add_parser("ai", help=t("help.ai"))
    ais = p.add_subparsers(dest="action")
    ais.add_parser("status")
    ais.add_parser("models")
    a = ais.add_parser("login")
    a.add_argument("--key-stdin", action="store_true", help=t("help.key_stdin"))
    a.add_argument("--store", action="store_true", help=t("help.store"))
    ais.add_parser("logout")
    ais.add_parser("commit-message")
    a = ais.add_parser("summary")
    a.add_argument("refs", nargs="*", metavar="REF")
    a.add_argument("--staged", action="store_true")

    sub.add_parser("menu", help=t("help.menu"))
    return parser


GLOBAL_FLAGS = {"-y", "--yes", "--allow-risky", "--non-interactive", "--batch", "--json", "--no-color", "-v", "--verbose"}
GLOBAL_VALUE_OPTS = {"-C", "--project", "--lang"}


def hoist_global_options(argv: Sequence[str]) -> List[str]:
    """Allow global options anywhere (``gitflow init -y``) by moving them before the command.

    Arguments after a literal ``--`` are never touched.
    """
    args = list(argv)
    end = args.index("--") if "--" in args else len(args)
    front: List[str] = []
    rest: List[str] = []
    i = 0
    while i < end:
        arg = args[i]
        if arg in GLOBAL_FLAGS:
            front.append(arg)
        elif arg in GLOBAL_VALUE_OPTS and i + 1 < end:
            front += [arg, args[i + 1]]
            i += 1
        elif arg.startswith(("--project=", "--lang=")):
            front.append(arg)
        else:
            rest.append(arg)
        i += 1
    return front + rest + args[end:]


def expand_aliases(argv: Sequence[str], aliases: Mapping[str, str]) -> List[str]:
    """Replace the first non-option argument if it is a configured alias."""
    args = list(argv)
    value_opts = {"-C", "--project", "--lang"}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in value_opts:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        if arg not in COMMANDS and arg in aliases:
            args[i:i + 1] = str(aliases[arg]).split()
        break
    return args
