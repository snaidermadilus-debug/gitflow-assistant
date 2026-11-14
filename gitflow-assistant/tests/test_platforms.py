"""Tests for platform detection, paths, validators and configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gitflow_assistant.core.configuration import ConfigError, Configuration, load_defaults, parse_simple_yaml
from gitflow_assistant.utils import os_detector, path_manager
from gitflow_assistant.utils.validators import (
    ValidationError,
    validate_branch_name,
    validate_email,
    validate_remote_name,
    validate_remote_url,
)


def test_termux_detection() -> None:
    assert os_detector.is_termux({"TERMUX_VERSION": "0.118"})
    assert os_detector.is_termux({"PREFIX": "/data/data/com.termux/files/usr"})
    assert not os_detector.is_termux({"PREFIX": "/usr"})


def test_platform_info_android_label() -> None:
    info = os_detector.detect_platform({"TERMUX_VERSION": "1", "SHELL": "/data/data/com.termux/files/usr/bin/bash"})
    assert info.is_termux and info.system == "android" and "Termux" in info.label and info.shell == "bash"


def test_shell_detection_windows() -> None:
    assert os_detector.detect_shell({"COMSPEC": r"C:\Windows\system32\cmd.exe", "PROMPT": "$P$G"}, "windows") == "cmd.exe"
    assert os_detector.detect_shell({"PSModulePath": "x"}, "windows") == "powershell"


def test_config_dir_override_and_xdg(tmp_path: Path) -> None:
    assert path_manager.config_dir({"GITFLOW_HOME": str(tmp_path)}) == tmp_path / "config"
    assert path_manager.data_dir({"GITFLOW_HOME": str(tmp_path)}) == tmp_path / "data"


def test_normalize_expands_user(isolated_env: Path) -> None:
    assert path_manager.normalize("~/x") == (isolated_env / "x").resolve()
    assert path_manager.normalize('"~/quoted dir"') == (isolated_env / "quoted dir").resolve()
    assert path_manager.is_within(isolated_env / "a" / "b", isolated_env)


@pytest.mark.parametrize("name", ["main", "feature/login", "fix-1.2"])
def test_valid_branch_names(name: str) -> None:
    assert validate_branch_name(name) == name


@pytest.mark.parametrize("name", ["", "-x", "a..b", "a b", "x.lock", "a/.b", "@", "a~1", "bad:name"])
def test_invalid_branch_names(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_branch_name(name)


def test_remote_validators() -> None:
    assert validate_remote_url("https://github.com/a/b.git")
    assert validate_remote_url("git@github.com:a/b.git")
    assert validate_remote_url("/tmp/remote.git")
    assert validate_remote_url(r"C:\repos\x.git")
    for bad in ("--upload-pack=x", "ext::sh -c evil", "https://x y"):
        with pytest.raises(ValidationError):
            validate_remote_url(bad)
    with pytest.raises(ValidationError):
        validate_remote_name("-o")
    with pytest.raises(ValidationError):
        validate_email("nope")


def test_mini_yaml_matches_pyyaml() -> None:
    yaml = pytest.importorskip("yaml")
    defaults_file = Path(__file__).resolve().parents[1] / "gitflow_assistant" / "config" / "defaults.yaml"
    text = defaults_file.read_text(encoding="utf-8")
    assert parse_simple_yaml(text) == yaml.safe_load(text)


def test_mini_yaml_features() -> None:
    data = parse_simple_yaml("a: 1\nempty:\nb:\n  c: true\n  d: [x, 'y z']\n  e:\n    - 1\n    - two\nf: ~\n")
    assert data == {"a": 1, "empty": {}, "b": {"c": True, "d": ["x", "y z"], "e": [1, "two"]}, "f": None}


def test_configuration_set_get_coerce_persist(tmp_path: Path) -> None:
    cfg = Configuration(path=tmp_path / "c.json")
    assert cfg.get("default_branch") == "main"
    cfg.set("timeouts.git", "30")
    cfg.set("security.block_secrets", "false")
    cfg.set("security.exclude_patterns", "dist/*, *.log")
    cfg.save()
    again = Configuration(path=tmp_path / "c.json")
    assert again.get("timeouts.git") == 30
    assert again.get("security.block_secrets") is False
    assert again.get("security.exclude_patterns") == ["dist/*", "*.log"]
    with pytest.raises(ConfigError):
        cfg.set("unknown.key", "1")
    with pytest.raises(ConfigError):
        cfg.set("timeouts.git", "abc")
    with pytest.raises(ConfigError, match="greater than zero"):
        cfg.set("timeouts.git", "0")
    with pytest.raises(ConfigError):
        cfg.set("github.token", "x")


def test_export_import_without_secrets(tmp_path: Path) -> None:
    cfg = Configuration(path=tmp_path / "c.json")
    cfg.set("language", "pt")
    cfg.set_alias("s", "status")
    out = cfg.export_to(tmp_path / "export.json")
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported["language"] == "pt" and "token" not in json.dumps(exported)
    (tmp_path / "in.json").write_text(json.dumps({"language": "es", "api_token": "secret", "bogus": 1,
                                                  "aliases": {"x": "doctor"}}), encoding="utf-8")
    other = Configuration(path=tmp_path / "o.json")
    ignored = other.import_from(tmp_path / "in.json")
    assert other.get("language") == "es" and other.get("aliases")["x"] == "doctor"
    assert set(ignored) == {"api_token", "bogus"}


def test_secret_key_variants_are_not_persisted(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"secret_key": "do-not-store", "gemini_key": "also-secret",
                                "public_key_id": "not-a-secret", "accessToken": "token",
                                "privateKey": "private", "apiKey": "api"}), encoding="utf-8")
    cfg = Configuration(path=path)
    assert cfg.user == {"public_key_id": "not-a-secret"}
    with pytest.raises(ConfigError):
        cfg.set("github.secret_key", "do-not-store")


def test_corrupt_config_is_reported_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("{broken", encoding="utf-8")
    cfg = Configuration(path=path)
    assert cfg.load_error and path.read_text(encoding="utf-8") == "{broken"


def test_defaults_load() -> None:
    assert load_defaults()["ai"]["model"] == "gemini-3.1-pro-preview"
