"""Configuration dataclass with defaults and CLI override support."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from translations import LANGUAGES, resolve_language

__all__ = ["BotConfig", "load_config"]

CONFIG_FILE: Final[Path] = Path("config.json")
_WORDLISTS_DIR: Final[Path] = Path("wordlists")


@dataclass
class BotConfig:
    """Central configuration for the BombParty bot."""

    language: str = "en"
    wordlist_path: Path = field(default_factory=lambda: _WORDLISTS_DIR / "en.txt")
    toggle_hotkey: str = "f8"
    window_title: str = "jklm.fun"
    typing_wpm_range: tuple[int, int] = (100, 130)
    typo_enabled: bool = True
    typo_probability: float = 0.04
    turbo: bool = False

    def __post_init__(self) -> None:
        if not self.toggle_hotkey:
            raise ValueError("toggle_hotkey must be a non-empty string")
        if not self.window_title:
            raise ValueError("window_title must be a non-empty string")

        wpm_min, wpm_max = self.typing_wpm_range
        if wpm_min <= 0 or wpm_max <= 0:
            raise ValueError(f"WPM values must be positive, got ({wpm_min}, {wpm_max})")
        if wpm_min > wpm_max:
            raise ValueError(f"wpm_min ({wpm_min}) must be <= wpm_max ({wpm_max})")
        if not 0.0 <= self.typo_probability <= 1.0:
            raise ValueError(
                f"typo_probability must be in [0, 1], got {self.typo_probability}"
            )


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="JKLM BombParty Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    lang_choices = ", ".join(f"{c} ({n})" for c, n in LANGUAGES.items())
    parser.add_argument(
        "--language",
        "-l",
        type=str,
        default=None,
        help=f"Language code or name. Sets wordlist to wordlists/{{code}}.txt. "
        f"Cannot be used with --wordlist. Choices: {lang_choices}",
    )
    parser.add_argument(
        "--wordlist",
        "-w",
        type=Path,
        default=None,
        help="Path to word list file (default: wordlists/en.txt). "
        "Cannot be used with --language.",
    )
    parser.add_argument(
        "--turbo",
        "-t",
        action="store_true",
        default=False,
        help="Remove all artificial delays (type as fast as possible)",
    )
    return parser


def _apply_json_config(config: BotConfig, data: dict[str, Any]) -> None:
    """Apply values from a parsed JSON config dict onto a BotConfig instance."""
    if "language" in data:
        code = resolve_language(str(data["language"]))
        config.language = code
        config.wordlist_path = _WORDLISTS_DIR / f"{code}.txt"
    if "wordlist_path" in data:
        config.wordlist_path = Path(data["wordlist_path"])
    if "toggle_hotkey" in data:
        config.toggle_hotkey = str(data["toggle_hotkey"]).lower()
    if "window_title" in data:
        config.window_title = str(data["window_title"])
    if "typing_wpm_range" in data:
        raw = data["typing_wpm_range"]
        if isinstance(raw, list) and len(raw) == 2:
            config.typing_wpm_range = (int(raw[0]), int(raw[1]))
    if "typo_enabled" in data:
        config.typo_enabled = bool(data["typo_enabled"])
    if "typo_probability" in data:
        config.typo_probability = float(data["typo_probability"])
    if "turbo" in data:
        config.turbo = bool(data["turbo"])
        if config.turbo:
            config.typo_enabled = False


def _apply_cli_args(config: BotConfig, args: argparse.Namespace) -> None:
    """Apply CLI argument overrides onto a BotConfig instance."""
    if args.language is not None and args.wordlist is not None:
        raise SystemExit("Error: --language and --wordlist cannot be used together.")

    if args.language is not None:
        code = resolve_language(args.language)
        config.language = code
        config.wordlist_path = _WORDLISTS_DIR / f"{code}.txt"
    if args.wordlist is not None:
        config.wordlist_path = args.wordlist
    if args.turbo:
        config.turbo = True
        config.typo_enabled = False


def load_config(argv: list[str] | None = None) -> BotConfig:
    """Load configuration: defaults → config.json → CLI args (highest priority)."""
    config = BotConfig()

    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as fh:
                _apply_json_config(config, json.load(fh))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"bad {CONFIG_FILE}, using defaults: {exc}")

    try:
        _apply_cli_args(config, _build_arg_parser().parse_args(argv))
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from None

    try:
        config.__post_init__()
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from None

    return config
