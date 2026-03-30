"""Human-like typing simulation with variable delays, burst patterns, and typo injection."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Callable, Final

from pynput.keyboard import Controller, Key

__all__ = ["type_word"]

if TYPE_CHECKING:
    from config import BotConfig
    from game_state import GameState

# QWERTY adjacent key mappings
ADJACENCY: Final[dict[str, tuple[str, ...]]] = {
    "a": ("q", "w", "s", "z"),
    "b": ("v", "g", "h", "n"),
    "c": ("x", "d", "f", "v"),
    "d": ("s", "e", "r", "f", "c", "x"),
    "e": ("w", "s", "d", "r"),
    "f": ("d", "r", "t", "g", "v", "c"),
    "g": ("f", "t", "y", "h", "b", "v"),
    "h": ("g", "y", "u", "j", "n", "b"),
    "i": ("u", "j", "k", "o"),
    "j": ("h", "u", "i", "k", "n", "m"),
    "k": ("j", "i", "o", "l", "m"),
    "l": ("k", "o", "p"),
    "m": ("n", "j", "k"),
    "n": ("b", "h", "j", "m"),
    "o": ("i", "k", "l", "p"),
    "p": ("o", "l"),
    "q": ("w", "a"),
    "r": ("e", "d", "f", "t"),
    "s": ("a", "w", "e", "d", "x", "z"),
    "t": ("r", "f", "g", "y"),
    "u": ("y", "h", "j", "i"),
    "v": ("c", "f", "g", "b"),
    "w": ("q", "a", "s", "e"),
    "x": ("z", "s", "d", "c"),
    "y": ("t", "g", "h", "u"),
    "z": ("a", "s", "x"),
}

_keyboard = Controller()

_CHARS_PER_WORD: Final[int] = 5
_JITTER_SECS: Final[float] = 0.025
_MIN_DELAY_SECS: Final[float] = 0.01

_LEFT_HAND: Final[frozenset[str]] = frozenset("qwertasdfgzxcvb")

_HAND_TRANSITION_MIN: Final[float] = 0.005
_HAND_TRANSITION_MAX: Final[float] = 0.020


def _sample_delay(config: BotConfig) -> float:
    """Sample a per-character delay (seconds) from a Gaussian fitted to the WPM range.

    When wpm_min == wpm_max the standard deviation is zero, producing a
    constant delay equal to the target WPM.
    """
    if config.turbo:
        return 0.0

    wpm_min, wpm_max = config.wpm
    mean_wpm = (wpm_min + wpm_max) / 2.0
    std_wpm = (wpm_max - wpm_min) / 4.0

    sampled_wpm = max(1.0, min(float(wpm_max), random.gauss(mean_wpm, std_wpm)))
    base_delay = 60.0 / (sampled_wpm * _CHARS_PER_WORD)
    jitter = random.triangular(-_JITTER_SECS, _JITTER_SECS, 0.0)
    return max(_MIN_DELAY_SECS, base_delay + jitter)


def _hand_transition_delay(prev_char: str | None, cur_char: str) -> float:
    """Return a small extra delay when consecutive keys use different hands."""
    if prev_char is None:
        return 0.0
    prev_left = prev_char.lower() in _LEFT_HAND
    cur_left = cur_char.lower() in _LEFT_HAND
    if prev_left != cur_left:
        return random.uniform(_HAND_TRANSITION_MIN, _HAND_TRANSITION_MAX)
    return 0.0


def _sleep_with_poll(
    delay_secs: float, can_continue: Callable[[], bool] | None
) -> bool:
    """Sleep with accurate OS-agnostic timing, checking can_continue frequently."""
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        remaining = delay_secs - elapsed

        if remaining <= 0:
            return True

        if can_continue is not None and not can_continue():
            return False

        if remaining > 0.02:
            time.sleep(0.015)
        else:
            time.sleep(remaining)


def _pick_typo_char(correct_char: str) -> str | None:
    """Pick an adjacent key for a realistic typo."""
    adjacent = ADJACENCY.get(correct_char.lower())
    return random.choice(adjacent) if adjacent else None


def _inject_adjacent_typo(char: str, can_continue: Callable[[], bool] | None) -> bool:
    """Hit a neighbouring key, notice, backspace, retype."""
    typo_char = _pick_typo_char(char)
    if not typo_char:
        return False

    _keyboard.press(typo_char)
    _keyboard.release(typo_char)
    if not _sleep_with_poll(random.uniform(0.200, 0.400), can_continue):
        return False

    _keyboard.press(Key.backspace)
    _keyboard.release(Key.backspace)
    if not _sleep_with_poll(random.uniform(0.100, 0.200), can_continue):
        return False
    return True


def _inject_double_tap(char: str, can_continue: Callable[[], bool] | None) -> bool:
    """Accidentally press the same key twice, notice, backspace."""
    _keyboard.press(char)
    _keyboard.release(char)
    if not _sleep_with_poll(random.uniform(0.200, 0.400), can_continue):
        return False

    _keyboard.press(Key.backspace)
    _keyboard.release(Key.backspace)
    if not _sleep_with_poll(random.uniform(0.100, 0.200), can_continue):
        return False
    return True


def _inject_transposition(
    char: str, next_char: str, can_continue: Callable[[], bool] | None
) -> bool:
    """Type two characters in the wrong order, then fix.

    Types next_char first (wrong), then char, then backspaces both
    and retypes char correctly. The caller types next_char afterward.
    Skips if both characters are identical (transposition would be invisible).
    """
    if char.lower() == next_char.lower():
        return False

    _keyboard.press(next_char)
    _keyboard.release(next_char)
    if not _sleep_with_poll(random.uniform(0.040, 0.080), can_continue):
        return False

    _keyboard.press(char)
    _keyboard.release(char)
    if not _sleep_with_poll(random.uniform(0.250, 0.450), can_continue):
        return False

    for _ in range(2):
        _keyboard.press(Key.backspace)
        _keyboard.release(Key.backspace)
        if not _sleep_with_poll(random.uniform(0.080, 0.150), can_continue):
            return False

    if not _sleep_with_poll(random.uniform(0.100, 0.200), can_continue):
        return False
    return True


def _try_inject_typo(
    char: str, next_char: str | None, can_continue: Callable[[], bool] | None
) -> bool:
    """Roll for a typo type and inject it.  Returns True if a typo occurred."""
    roll = random.random()
    if roll < 0.30 and next_char is not None:
        return _inject_transposition(char, next_char, can_continue)
    if roll < 0.45:
        return _inject_double_tap(char, can_continue)
    return _inject_adjacent_typo(char, can_continue)


def type_word(
    word: str,
    config: BotConfig,
    state: GameState,
    *,
    can_continue: Callable[[], bool] | None = None,
) -> bool:
    """Type a word character-by-character with human-like timing, then press Enter.

    Args:
        word: The word to type.
        config: Bot configuration (controls WPM, typo injection, turbo mode).
        state: Game state (checked for ``is_active`` before each keystroke).
        can_continue: Optional guard called before every keystroke.  If it
            returns False, typing stops and this function returns False.

    Returns:
        True if the word was fully typed and Enter was pressed, False if
        aborted mid-type.
    """
    if not word:
        return True

    _keyboard.press(Key.ctrl)
    _keyboard.press("a")
    _keyboard.release("a")
    _keyboard.release(Key.ctrl)
    time.sleep(0.02)
    _keyboard.press(Key.backspace)
    _keyboard.release(Key.backspace)
    time.sleep(0.02)

    turbo = config.turbo
    typo_count = 0
    max_typos = 2 if len(word) >= 10 else 1
    burst_counter = 0
    next_burst_at = random.randint(3, 8)
    prev_char: str | None = None

    for i, char in enumerate(word):
        if not state.is_active:
            return False
        if can_continue is not None and not can_continue():
            return False

        if (
            not turbo
            and config.typo > 0
            and typo_count < max_typos
            and 0 < i < len(word) - 1
            and random.random() < config.typo
        ):
            next_char = word[i + 1] if i + 1 < len(word) - 1 else None
            typo_result = _try_inject_typo(char, next_char, can_continue)
            if can_continue is not None and not can_continue():
                return False
            if typo_result:
                typo_count += 1

        _keyboard.press(char)
        _keyboard.release(char)

        if not turbo:
            delay = _sample_delay(config)
            delay += _hand_transition_delay(prev_char, char)
            burst_counter += 1
            if burst_counter >= next_burst_at:
                delay += random.uniform(0.030, 0.110)
                burst_counter = 0
                next_burst_at = random.randint(3, 8)
            if not _sleep_with_poll(delay, can_continue):
                return False

        prev_char = char

    if not state.is_active:
        return False
    if can_continue is not None and not can_continue():
        return False

    if not config.turbo:
        if not _sleep_with_poll(random.uniform(0.030, 0.090), can_continue):
            return False

    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    return True
