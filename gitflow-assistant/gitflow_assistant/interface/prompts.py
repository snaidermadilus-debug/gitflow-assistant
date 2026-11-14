"""Interactive prompts and the console implementation of ``UserInterface``."""

from __future__ import annotations

from typing import Callable, ContextManager, List, Sequence

from gitflow_assistant.i18n import t
from gitflow_assistant.interface.output import Output
from gitflow_assistant.security.confirmation import ConfirmationPolicy
from gitflow_assistant.services.errors import Cancelled, UsageError

YES = {"y", "yes", "s", "sim", "si", "sí"}
NO = {"n", "no", "nao", "não"}


def parse_selection(text: str, count: int, default_all: bool = True) -> List[int]:
    """Parse ``"1,3-5"``, ``"a"`` (all) or ``"n"`` (none) into zero-based indexes.

    Raises ``ValueError`` on invalid input.
    """
    text = text.strip().lower()
    if not text:
        return list(range(count)) if default_all else []
    if text in ("a", "all", "*", "t", "todos", "todo"):
        return list(range(count))
    if text in ("n", "none", "nenhum", "ninguno", "0"):
        return []
    result: List[int] = []
    for part in text.replace(" ", ",").split(","):
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                start, end = end, start
            numbers = range(start, end + 1)
        else:
            numbers = range(int(part), int(part) + 1)
        for number in numbers:
            if number < 1 or number > count:
                raise ValueError(f"out of range: {number}")
            if number - 1 not in result:
                result.append(number - 1)
    return sorted(result)


class ConsoleUI:
    """Console user interface used by both the CLI and the TUI."""

    def __init__(self, out: Output, interactive: bool, mode: str = "risky", assume_yes: bool = False,
                 allow_risky: bool = False, reader: Callable[[str], str] = input) -> None:
        self.out = out
        self.interactive = interactive
        self._read = reader
        self.policy = ConfirmationPolicy(ask=self._ask_yes_no if interactive else None,
                                         ask_phrase=self._ask_phrase if interactive else None,
                                         mode=mode, assume_yes=assume_yes, allow_risky=allow_risky)

    # --------------------------------------------------------- messages
    def info(self, message: str) -> None:
        self.out.info(message)

    def success(self, message: str) -> None:
        self.out.success(message)

    def warning(self, message: str) -> None:
        self.out.warning(message)

    def error(self, message: str) -> None:
        self.out.error(message)

    def heading(self, message: str) -> None:
        self.out.heading(message)

    def table(self, title: str, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        self.out.table(title, headers, rows)

    def text_block(self, text: str, syntax: str = "") -> None:
        self.out.text_block(text, syntax)

    def progress(self, message: str) -> ContextManager[None]:
        return self.out.progress(message)

    # ----------------------------------------------------------- input
    def _input(self, prompt: str) -> str:
        if not self.interactive:
            raise UsageError(t("err.non_interactive_input", prompt=prompt.strip()))
        try:
            return self._read(prompt)
        except EOFError as exc:
            raise Cancelled(t("common.cancelled")) from exc

    def ask(self, question: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = self._input(f"? {question}{suffix}: ").strip()
        return answer or default

    def _ask_yes_no(self, question: str, default: bool) -> bool:
        hint = t("prompt.yes_no_default_yes") if default else t("prompt.yes_no_default_no")
        while True:
            answer = self._input(f"? {question} {hint} ").strip().lower()
            if not answer:
                return default
            if answer in YES:
                return True
            if answer in NO:
                return False
            self.out.warning(t("prompt.invalid"))

    def _ask_phrase(self, text: str, phrase: str) -> bool:
        self.out.warning(text)
        expected = {phrase, t("confirm.phrase")}
        answer = self._input(f"? {t('confirm.type_phrase', phrase=t('confirm.phrase'))} ").strip().lower()
        return answer in expected

    def confirm(self, question: str, default: bool = True) -> bool:
        return self.policy.confirm(question, default)

    def confirm_risky(self, action: str, consequences: Sequence[str]) -> bool:
        return self.policy.confirm_risky(action, consequences)

    def choose(self, question: str, options: Sequence[str], default: int = 0) -> int:
        if not self.interactive:
            raise UsageError(t("err.non_interactive_input", prompt=question))
        self.out.print(f"? {question}")
        for i, option in enumerate(options, start=1):
            marker = "*" if i - 1 == default else " "
            self.out.print(f"  {marker}[{i}] {option}")
        while True:
            answer = self._input(f"  {t('prompt.choice')} [{default + 1}]: ").strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            self.out.warning(t("prompt.invalid"))

    def select_many(self, question: str, items: Sequence[str], default_all: bool = True) -> List[int]:
        """Ask for a selection; the caller is responsible for displaying the numbered items."""
        hint = t("prompt.selection_hint")
        while True:
            answer = self._input(f"? {question} ({hint}) [{'a' if default_all else 'n'}]: ")
            try:
                return parse_selection(answer, len(items), default_all)
            except ValueError:
                self.out.warning(t("prompt.invalid"))
