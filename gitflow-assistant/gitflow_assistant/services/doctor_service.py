"""System diagnostics (``gitflow doctor``)."""

from __future__ import annotations

import importlib.util
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from gitflow_assistant.core.git_engine import GitEngine
from gitflow_assistant.i18n import t
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.utils.os_detector import detect_platform
from gitflow_assistant.utils.path_manager import config_dir, data_dir

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    """Result of one diagnostic check."""

    name: str
    status: str
    detail: str
    suggestion: str = ""


def check_connectivity(host: str = "api.github.com", port: int = 443, timeout: float = 5.0) -> Optional[str]:
    """Return None if a TCP connection succeeds, otherwise the error text."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as exc:
        return str(exc)


def run_diagnostics(ctx: AppContext, network: bool = True) -> List[Check]:
    """Run every check; never raises for an individual failing check."""
    checks: List[Check] = []
    plat = detect_platform()
    checks.append(Check(t("doctor.platform"), OK, f"{plat.label}, Python {plat.python_version}, shell {plat.shell}"))
    if sys.version_info < (3, 9):
        checks.append(Check("Python", FAIL, sys.version.split()[0], t("doctor.python_old")))
    engine = GitEngine(Path.cwd())
    version = engine.version()
    if not version:
        checks.append(Check("Git", FAIL, t("doctor.git_missing"), t("doctor.git_install", cmd=_git_install_cmd(plat))))
        return checks
    vtext = ".".join(map(str, version))
    checks.append(Check("Git", OK if version >= (2, 23) else WARN, vtext,
                        "" if version >= (2, 23) else t("doctor.git_old")))
    for key in ("user.name", "user.email"):
        value = engine.get_config(key, global_scope=True)
        checks.append(Check(f"git {key}", OK if value else WARN, value or t("doctor.not_set"),
                            "" if value else t("doctor.set_identity", key=key)))
    default_branch = engine.get_config("init.defaultBranch", global_scope=True)
    checks.append(Check("init.defaultBranch", OK if default_branch else WARN, default_branch or t("doctor.not_set"),
                        "" if default_branch else "git config --global init.defaultBranch main"))
    helper = engine.get_config("credential.helper", global_scope=True)
    checks.append(Check("credential.helper", OK if helper else WARN, helper or t("doctor.not_set"),
                        "" if helper else t("doctor.helper_hint")))
    for module, label in (("rich", "Rich"), ("yaml", "PyYAML"), ("keyring", "keyring")):
        found = importlib.util.find_spec(module) is not None
        checks.append(Check(label, OK if found else WARN, t("doctor.installed") if found else t("doctor.optional_missing"),
                            "" if found else t("doctor.optional_hint", pkg=label.lower() if label != "PyYAML" else "pyyaml")))
    checks.append(Check("gh (GitHub CLI)", OK if ctx.credentials.gh_available() else WARN,
                        t("doctor.installed") if ctx.credentials.gh_available() else t("doctor.optional_missing")))
    token = ctx.credentials.resolve(allow_credential_helper=False)
    checks.append(Check(t("doctor.auth"), OK if token else WARN,
                        f"{token.source} ({token.masked})" if token else t("doctor.no_token"),
                        "" if token else t("hint.auth1")))
    if plat.is_termux:
        storage = Path.home() / "storage"
        checks.append(Check("termux-setup-storage", OK if storage.exists() else WARN,
                            str(storage) if storage.exists() else t("doctor.not_set"),
                            "" if storage.exists() else t("doctor.termux_storage")))
    checks.append(Check(t("doctor.config_dir"), OK, str(config_dir())))
    checks.append(Check(t("doctor.data_dir"), OK, str(data_dir())))
    if ctx.config.load_error:
        checks.append(Check(t("doctor.config_file"), FAIL, ctx.config.load_error, t("doctor.config_fix")))
    if network:
        error = check_connectivity()
        checks.append(Check(t("doctor.connectivity"), OK if error is None else WARN,
                            "api.github.com:443" if error is None else error,
                            "" if error is None else t("hint.net1")))
    checks += _project_checks(ctx, network)
    return checks


def _project_checks(ctx: AppContext, network: bool) -> List[Check]:
    checks: List[Check] = []
    path = ctx.project_path()
    if not path:
        return [Check(t("doctor.project"), WARN, t("doctor.no_project"), "gitflow select <path>")]
    engine = ctx.engine(path)
    probe = engine.run(["rev-parse", "--show-toplevel"]) if path.is_dir() else None
    if probe is not None and not probe.ok and "dubious ownership" in probe.stderr:
        return [Check(t("doctor.project"), FAIL, t("doctor.dubious"),
                      f"git config --global --add safe.directory \"{path}\"")]
    if probe is None or not probe.ok:
        return [Check(t("doctor.project"), WARN, t("doctor.not_repo", path=str(path)), "gitflow init")]
    engine.cwd = Path(probe.stdout.strip())
    checks.append(Check(t("doctor.project"), OK, str(engine.cwd)))
    remotes = engine.remotes()
    checks.append(Check(t("doctor.remotes"), OK if remotes else WARN,
                        ", ".join(f"{n}={u.get('push', '')}" for n, u in remotes.items()) or t("doctor.not_set"),
                        "" if remotes else "gitflow remote set origin <url>"))
    conflicts = engine.conflicts()
    op = engine.operation_in_progress()
    checks.append(Check(t("doctor.conflicts"), FAIL if conflicts or op else OK,
                        ", ".join(conflicts) or (op or t("doctor.none")),
                        t("hint.conf1") if conflicts or op else ""))
    if engine.current_branch() and engine.has_commits() and not engine.upstream() and remotes:
        checks.append(Check("upstream", WARN, t("doctor.no_upstream"), "gitflow push"))
    if network and ctx.remote_name in remotes:
        res = engine.ls_remote(ctx.remote_name)
        checks.append(Check(t("doctor.remote_access"), OK if res.ok else WARN,
                            t("doctor.reachable") if res.ok else res.error_text()[:200],
                            "" if res.ok else t("hint.auth1")))
    integrity = engine.verify_integrity()
    checks.append(Check(t("doctor.integrity"), OK if integrity.ok else FAIL,
                        t("doctor.ok") if integrity.ok else integrity.error_text()[:200]))
    return checks


def _git_install_cmd(plat) -> str:  # type: ignore[no-untyped-def]
    if plat.is_termux:
        return "pkg install git"
    if plat.is_windows:
        return "winget install --id Git.Git -e"
    return "sudo apt install git  (or your distribution's package manager)"
