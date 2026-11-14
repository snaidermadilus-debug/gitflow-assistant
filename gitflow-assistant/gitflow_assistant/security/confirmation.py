"""Explicit confirmation policy for write and risky operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence


class ConfirmationRequired(RuntimeError):
    """A risky operation was requested without authorisation (non-interactive mode)."""


class OperationCancelled(RuntimeError):
    """The user declined the operation."""


@dataclass
class ConfirmationPolicy:
    """Decide whether an operation may proceed.

    * ``mode="always"``: every write operation is confirmed.
    * ``mode="risky"``: only risky operations are confirmed.
    * ``assume_yes``: non-risky confirmations are auto-accepted (``--yes``).
    * Risky operations in non-interactive mode require ``assume_yes`` *and*
      ``allow_risky`` (``--yes --allow-risky``).
    """

    ask: Optional[Callable[[str, bool], bool]]
    ask_phrase: Optional[Callable[[str, str], bool]] = None
    mode: str = "risky"
    assume_yes: bool = False
    allow_risky: bool = False

    @property
    def interactive(self) -> bool:
        return self.ask is not None

    def confirm(self, question: str, default: bool = True) -> bool:
        """Confirm a normal write operation."""
        if self.assume_yes:
            return True
        if self.mode != "always" and not self.interactive:
            return True
        if not self.interactive:
            raise ConfirmationRequired(f"confirmation required: {question} (use --yes)")
        assert self.ask is not None
        return self.ask(question, default)

    def confirm_risky(self, action: str, consequences: Sequence[str], phrase: str = "yes") -> bool:
        """Confirm a risky operation, explaining its consequences.

        Interactive users must type ``phrase``; scripts need ``--yes --allow-risky``.
        """
        if not self.interactive:
            if self.assume_yes and self.allow_risky:
                return True
            raise ConfirmationRequired(f"risky operation '{action}' requires --yes --allow-risky")
        text = action + "\n" + "\n".join(f"  - {c}" for c in consequences)
        if self.ask_phrase is not None:
            return self.ask_phrase(text, phrase)
        assert self.ask is not None
        return self.ask(text, False)
