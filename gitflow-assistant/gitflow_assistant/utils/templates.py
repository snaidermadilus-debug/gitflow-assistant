"""Generators for ``.gitignore``, ``README.md`` and commit message templates."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Sequence

COMMON_IGNORE = [
    "# Secrets & local environment",
    ".env",
    ".env.*",
    "!.env.example",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "",
    "# OS / editors",
    ".DS_Store",
    "Thumbs.db",
    ".idea/",
    ".vscode/",
    "*.swp",
    "*~",
    "*.bak",
    "*.tmp",
    "",
    "# Logs",
    "*.log",
]

LANGUAGE_IGNORE: Dict[str, List[str]] = {
    "python": [
        "__pycache__/", "*.py[cod]", ".venv/", "venv/", "env/", "build/", "dist/",
        "*.egg-info/", ".pytest_cache/", ".mypy_cache/", ".coverage", "htmlcov/",
    ],
    "node": ["node_modules/", "npm-debug.log*", "yarn-error.log*", ".npm/", "dist/", "build/", ".next/", "coverage/"],
    "java": ["*.class", "target/", "build/", ".gradle/", "*.jar", "*.war", "out/"],
    "go": ["bin/", "*.exe", "*.test", "*.out", "vendor/"],
    "rust": ["target/", "**/*.rs.bk"],
    "php": ["vendor/", "composer.phar", ".phpunit.result.cache"],
    "dotnet": ["bin/", "obj/", "*.user", "*.suo", ".vs/"],
    "android": ["*.apk", "*.aab", ".gradle/", "local.properties", "build/", "captures/", "*.jks", "*.keystore"],
    "flutter": [".dart_tool/", ".flutter-plugins", ".flutter-plugins-dependencies", "build/", ".packages"],
    "c_cpp": ["*.o", "*.obj", "*.so", "*.dll", "*.a", "*.lib", "*.exe", "build/", "cmake-build-*/"],
    "ruby": ["/.bundle/", "/vendor/bundle", "*.gem", "/coverage/"],
}

# file marker -> language
LANGUAGE_MARKERS: Dict[str, str] = {
    "pyproject.toml": "python", "requirements.txt": "python", "setup.py": "python", "Pipfile": "python",
    "package.json": "node", "pom.xml": "java", "build.gradle": "java", "build.gradle.kts": "java",
    "go.mod": "go", "Cargo.toml": "rust", "composer.json": "php", "pubspec.yaml": "flutter",
    "CMakeLists.txt": "c_cpp", "Makefile": "c_cpp", "Gemfile": "ruby", "AndroidManifest.xml": "android",
}
EXTENSION_MARKERS: Dict[str, str] = {
    ".py": "python", ".js": "node", ".ts": "node", ".java": "java", ".kt": "java", ".go": "go",
    ".rs": "rust", ".php": "php", ".cs": "dotnet", ".csproj": "dotnet", ".dart": "flutter",
    ".c": "c_cpp", ".cpp": "c_cpp", ".h": "c_cpp", ".rb": "ruby",
}

COMMIT_TEMPLATES: Dict[str, str] = {
    "feat": "feat: ",
    "fix": "fix: ",
    "docs": "docs: ",
    "style": "style: ",
    "refactor": "refactor: ",
    "test": "test: ",
    "chore": "chore: ",
    "perf": "perf: ",
    "ci": "ci: ",
    "build": "build: ",
}

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", "target", ".gradle"}


def detect_languages(project: Path, max_depth: int = 2, max_entries: int = 3000) -> List[str]:
    """Detect project languages from marker files and extensions (bounded walk)."""
    found: Dict[str, None] = {}
    seen = 0
    stack = [(project, 0)]
    while stack and seen < max_entries:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if entry.is_dir():
                if depth < max_depth and entry.name not in _SKIP_DIRS and not entry.is_symlink():
                    stack.append((entry, depth + 1))
                continue
            lang = LANGUAGE_MARKERS.get(entry.name) or EXTENSION_MARKERS.get(entry.suffix.lower())
            if lang:
                found[lang] = None
    return sorted(found)


def build_gitignore(languages: Iterable[str]) -> str:
    """Build ``.gitignore`` content for the given languages."""
    lines: List[str] = list(COMMON_IGNORE)
    for lang in languages:
        rules = LANGUAGE_IGNORE.get(lang)
        if rules:
            lines += ["", f"# {lang}"] + rules
    return "\n".join(lines) + "\n"


def merge_gitignore(existing: str, generated: str) -> str:
    """Append only the generated rules that are not already present."""
    present = {line.strip() for line in existing.splitlines()}
    additions = [line for line in generated.splitlines() if line.strip() and not line.startswith("#") and line.strip() not in present]
    if not additions:
        return existing
    sep = "" if existing.endswith("\n") or not existing else "\n"
    return existing + sep + "\n# Added by GitFlow Assistant\n" + "\n".join(additions) + "\n"


def build_readme(name: str, description: str, languages: Sequence[str], license_name: str = "MIT",
                 install_cmd: str = "", usage_cmd: str = "") -> str:
    """Generate a README.md skeleton filled with real project information."""
    tech = ", ".join(languages) if languages else "-"
    install = install_cmd or _default_install(languages)
    usage = usage_cmd or "Describe how to run the project here."
    return (
        f"# {name}\n\n"
        f"{description or 'Project description.'}\n\n"
        "## Technologies\n\n"
        f"{tech}\n\n"
        "## Installation\n\n"
        f"```bash\ngit clone <repository-url>\ncd {name}\n{install}\n```\n\n"
        "## Usage\n\n"
        f"{usage}\n\n"
        "## Contributing\n\n"
        "1. Fork the repository\n2. Create a branch (`git checkout -b feature/my-feature`)\n"
        "3. Commit your changes\n4. Open a Pull Request\n\n"
        "## License\n\n"
        f"{license_name}\n"
    )


def _default_install(languages: Sequence[str]) -> str:
    if "python" in languages:
        return "pip install -r requirements.txt"
    if "node" in languages:
        return "npm install"
    if "rust" in languages:
        return "cargo build"
    if "go" in languages:
        return "go build ./..."
    return "# installation steps"
