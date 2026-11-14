"""Heuristic secret detection on file names and text content.

Results are *heuristic*: a clean scan is never a guarantee that a file is
free of secrets, and matches can be false positives.
"""

from __future__ import annotations

import fnmatch
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Pattern, Tuple

CONFIRMED = "secret"
SUSPICIOUS = "suspicious"


@dataclass(frozen=True)
class ContentRule:
    """A regular-expression rule applied line by line."""

    rule_id: str
    pattern: Pattern[str]
    level: str  # CONFIRMED (high precision) or SUSPICIOUS
    description: str


CONTENT_RULES: Tuple[ContentRule, ...] = (
    ContentRule("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY( BLOCK)?-----"),
                CONFIRMED, "private key block"),
    ContentRule("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
                CONFIRMED, "GitHub token"),
    ContentRule("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), CONFIRMED, "AWS access key id"),
    ContentRule("aws-secret-key", re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}"),
                CONFIRMED, "AWS secret access key"),
    ContentRule("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), CONFIRMED, "Google API key"),
    ContentRule("slack-token", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"), CONFIRMED, "Slack token"),
    ContentRule("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b"), CONFIRMED, "Stripe live key"),
    ContentRule("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}\b"), CONFIRMED, "OpenAI-style API key"),
    ContentRule("telegram-bot-token", re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_\-]{33}\b"), CONFIRMED, "Telegram bot token"),
    ContentRule("url-credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{3,}@[^\s/]+", re.IGNORECASE),
                CONFIRMED, "credentials embedded in URL"),
    ContentRule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
                SUSPICIOUS, "JSON Web Token"),
    ContentRule("generic-assignment", re.compile(
        r"(?i)\b[\w.-]*(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
        r"[\w.-]*\s*[:=]\s*['\"]?(?P<value>[^\s'\"#,;]{6,})"), SUSPICIOUS, "hard-coded credential assignment"),
)

PLACEHOLDER = re.compile(r"(?i)^(?:x+|\*+|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|changeme|change_me|example|your[_-].*|"
                         r"dummy|test|placeholder|none|null|true|false|password|secret|os\.environ.*|getenv.*|process\.env.*)$")

# file-name rules: (glob, level, description)
NAME_RULES: Tuple[Tuple[str, str, str], ...] = (
    (".env", CONFIRMED, "environment file"),
    (".env.*", CONFIRMED, "environment file"),
    ("*.pem", CONFIRMED, "PEM certificate/key"),
    ("*.key", CONFIRMED, "private key file"),
    ("*.p12", CONFIRMED, "PKCS#12 keystore"),
    ("*.pfx", CONFIRMED, "PKCS#12 keystore"),
    ("*.jks", CONFIRMED, "Java keystore"),
    ("*.keystore", CONFIRMED, "keystore"),
    ("id_rsa", CONFIRMED, "SSH private key"),
    ("id_dsa", CONFIRMED, "SSH private key"),
    ("id_ecdsa", CONFIRMED, "SSH private key"),
    ("id_ed25519", CONFIRMED, "SSH private key"),
    (".netrc", CONFIRMED, "netrc credentials"),
    (".git-credentials", CONFIRMED, "git credentials store"),
    (".pypirc", SUSPICIOUS, "PyPI configuration"),
    (".npmrc", SUSPICIOUS, "npm configuration (may contain tokens)"),
    ("credentials*", SUSPICIOUS, "credentials file"),
    ("secrets.*", SUSPICIOUS, "secrets file"),
    ("*secret*.json", SUSPICIOUS, "secrets file"),
    ("service-account*.json", SUSPICIOUS, "cloud service account"),
    ("*.tfstate", SUSPICIOUS, "Terraform state (may contain secrets)"),
    ("*.sqlite", SUSPICIOUS, "database file"),
    ("*.db", SUSPICIOUS, "database file"),
    ("*.bak", SUSPICIOUS, "backup file"),
    ("*.backup", SUSPICIOUS, "backup file"),
    ("*.old", SUSPICIOUS, "backup file"),
    ("*.swp", SUSPICIOUS, "editor swap file"),
    ("*~", SUSPICIOUS, "editor backup file"),
    ("*.dump", SUSPICIOUS, "dump file"),
)
SAFE_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}


@dataclass(frozen=True)
class SecretMatch:
    """A secret candidate found in content or name."""

    rule_id: str
    level: str
    description: str
    line: int
    excerpt: str
    fingerprint: str


def mask_value(value: str) -> str:
    """Show only the first and last characters of a sensitive value."""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * min(12, len(value) - 6)}{value[-2:]}"


def fingerprint(path: str, rule_id: str, secret: str) -> str:
    """Stable identifier for a finding, used to record false positives."""
    return hashlib.sha256(f"{path}\x00{rule_id}\x00{secret}".encode("utf-8", "replace")).hexdigest()[:16]


def shannon_entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts = {ch: value.count(ch) for ch in set(value)}
    return -sum((c / len(value)) * math.log2(c / len(value)) for c in counts.values())


def check_name(path: str) -> Optional[Tuple[str, str, str]]:
    """Return ``(rule_glob, level, description)`` if the file name is sensitive."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name in SAFE_NAMES:
        return None
    for glob, level, description in NAME_RULES:
        if fnmatch.fnmatchcase(name, glob) or fnmatch.fnmatchcase(name.lower(), glob):
            return glob, level, description
    return None


def scan_lines(path: str, lines: Iterable[str]) -> Iterator[SecretMatch]:
    """Apply content rules to an iterable of text lines."""
    for number, line in enumerate(lines, start=1):
        if len(line) > 4000:
            line = line[:4000]
        for rule in CONTENT_RULES:
            for match in rule.pattern.finditer(line):
                secret = match.groupdict().get("value") or match.group(0)
                level = rule.level
                if rule.rule_id == "generic-assignment":
                    cleaned = secret.strip("'\"")
                    if PLACEHOLDER.match(cleaned) or cleaned.startswith(("$", "%", "{", "os.", "env")):
                        continue
                    if shannon_entropy(cleaned) >= 3.5 and len(cleaned) >= 16:
                        level = CONFIRMED
                yield SecretMatch(rule.rule_id, level, rule.description, number,
                                  line.strip()[:120].replace(secret, mask_value(secret)),
                                  fingerprint(path, rule.rule_id, secret))


def matches_any(path: str, patterns: List[str]) -> bool:
    """True if ``path`` (posix style) or its name matches any glob."""
    posix = path.replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(posix, p) or fnmatch.fnmatch(name, p) or posix.startswith(p.rstrip("/") + "/")
               for p in patterns if p)
