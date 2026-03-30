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
    hotkey: str = "f8"
    wpm: tuple[int, int] = (100, 130)
    typo: float = 0.04
    surrender: float = 0.50
    turbo: bool = False

    def __post_init__(self) -> None:
        if not self.hotkey:
            raise ValueError("hotkey must be a non-empty string")

        wpm_min, wpm_max = self.wpm
        if wpm_min <= 0 or wpm_max <= 0:
            raise ValueError(f"WPM values must be positive, got ({wpm_min}, {wpm_max})")
        if wpm_min > wpm_max:
            raise ValueError(f"wpm min ({wpm_min}) must be <= max ({wpm_max})")
        if not 0.0 <= self.typo <= 1.0:
            raise ValueError(f"typo must be in [0, 1], got {self.typo}")
        if not 0.0 <= self.surrender <= 1.0:
            raise ValueError(f"surrender must be in [0, 1], got {self.surrender}")


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
        "--hotkey",
        "-k",
        type=str,
        default=None,
        metavar="KEY",
        help="Global toggle hotkey (default: f8)",
    )
    parser.add_argument(
        "--wpm",
        nargs=2,
        type=int,
        default=None,
        metavar=("MIN", "MAX"),
        help="WPM range for keystroke timing (default: 100 130)",
    )
    parser.add_argument(
        "--typo",
        type=float,
        default=None,
        metavar="RATE",
        help="Per-keystroke typo probability 0.0-1.0 (default: 0.04, 0 to disable)",
    )
    parser.add_argument(
        "--surrender",
        "-s",
        type=float,
        default=None,
        metavar="RATE",
        help="Probability of /suicide when no word is found 0.0-1.0 (default: 0.5)",
    )
    parser.add_argument(
        "--turbo",
        "-t",
        action="store_true",
        default=False,
        help="Disable all timing simulation (type as fast as possible)",
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
    if "hotkey" in data:
        config.hotkey = str(data["hotkey"]).lower()
    if "wpm" in data:
        raw = data["wpm"]
        if isinstance(raw, list) and len(raw) == 2:
            config.wpm = (int(raw[0]), int(raw[1]))
    if "typo" in data:
        config.typo = float(data["typo"])
    if "surrender" in data:
        config.surrender = float(data["surrender"])
    if "turbo" in data:
        config.turbo = bool(data["turbo"])
        if config.turbo:
            config.typo = 0.0


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
    if args.hotkey is not None:
        config.hotkey = args.hotkey.lower()
    if args.wpm is not None:
        config.wpm = (args.wpm[0], args.wpm[1])
    if args.typo is not None:
        config.typo = args.typo
    if args.surrender is not None:
        config.surrender = args.surrender
    if args.turbo:
        config.turbo = True
        config.typo = 0.0


def load_config(argv: list[str] | None = None) -> BotConfig:
    """Load configuration: defaults -> config.json -> CLI args (highest priority)."""
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
