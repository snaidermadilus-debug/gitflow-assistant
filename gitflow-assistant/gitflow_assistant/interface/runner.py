"""Execute a parsed command and map exceptions to exit codes and messages."""

from __future__ import annotations

import argparse
import logging

from gitflow_assistant.core.configuration import ConfigError
from gitflow_assistant.core.git_engine import GitError, GitNotInstalledError
from gitflow_assistant.core.github_client import GitHubAuthError, GitHubError, GitHubRateLimitError
from gitflow_assistant.i18n import t
from gitflow_assistant.security.confirmation import ConfirmationRequired, OperationCancelled
from gitflow_assistant.services.context import AppContext
from gitflow_assistant.services.errors import ServiceError
from gitflow_assistant.utils.validators import ValidationError

log = logging.getLogger("gitflow.app")

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_GIT, EXIT_NO_REPO, EXIT_CANCEL, EXIT_SECURITY, EXIT_REMOTE = 0, 1, 2, 3, 4, 5, 6, 7
EXIT_INTERRUPT = 130


def execute(ctx: AppContext, args: argparse.Namespace) -> int:
    """Run the handler for ``args.command`` with uniform error reporting."""
    from gitflow_assistant.interface.commands import HANDLERS

    handler = HANDLERS[args.command]
    ui = ctx.ui
    try:
        code = handler(ctx, args)
        log.info("command %s exit=%s", args.command, code)
        return code
    except GitNotInstalledError as exc:
        ui.error(str(exc))
        ui.info(t("doctor.git_install_hint"))
        return EXIT_NO_GIT
    except ServiceError as exc:
        ui.error(str(exc))
        if exc.exit_code == EXIT_NO_REPO:
            ui.info(t("hint.select_project"))
        return exc.exit_code
    except (ValidationError, ConfigError, ConfirmationRequired) as exc:
        ui.error(str(exc))
        return EXIT_USAGE
    except OperationCancelled as exc:
        ui.warning(str(exc) or t("common.cancelled"))
        return EXIT_CANCEL
    except GitHubRateLimitError as exc:
        ui.error(str(exc))
        if exc.reset_at:
            import time
            ui.info(t("github.rate_reset", when=time.strftime("%H:%M:%S", time.localtime(exc.reset_at))))
        return EXIT_REMOTE
    except GitHubAuthError as exc:
        ui.error(str(exc))
        for hint in (t("hint.auth1"), t("hint.auth2"), t("hint.auth3")):
            ui.info("  • " + hint)
        return EXIT_REMOTE
    except GitHubError as exc:
        ui.error(str(exc))
        return EXIT_REMOTE
    except GitError as exc:
        ui.error(str(exc))
        log.warning("git error in %s: %s", args.command, exc)
        return EXIT_FAIL
    except OSError as exc:
        ui.error(t("err.os", error=str(exc)))
        return EXIT_FAIL
