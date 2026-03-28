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

# QWERTY keyboard adjacency map for typo simulation.
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

# Keys reachable by each hand on a standard QWERTY layout.
_LEFT_HAND: Final[frozenset[str]] = frozenset("qwertasdfgzxcvb")

# Extra delay when consecutive keys require different hands.
_HAND_TRANSITION_MIN: Final[float] = 0.005
_HAND_TRANSITION_MAX: Final[float] = 0.020


def _sample_delay(config: BotConfig) -> float:
    """Sample a per-character delay (seconds) from a Gaussian fitted to the WPM range.

    When wpm_min == wpm_max the standard deviation is zero, producing a
    constant delay equal to the target WPM.
    """
    if config.turbo:
        return 0.0

    wpm_min, wpm_max = config.typing_wpm_range
    mean_wpm = (wpm_min + wpm_max) / 2.0
    std_wpm = (wpm_max - wpm_min) / 4.0

    sampled_wpm = max(wpm_min, min(wpm_max, random.gauss(mean_wpm, std_wpm)))
    base_delay = 60.0 / (sampled_wpm * _CHARS_PER_WORD)
    # Triangular jitter biases toward zero — most keystrokes are close to
    # the base delay, with occasional slower or faster outliers.
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


def _pick_typo_char(correct_char: str) -> str | None:
    """Pick an adjacent key for a realistic typo."""
    adjacent = ADJACENCY.get(correct_char.lower())
    return random.choice(adjacent) if adjacent else None


def _inject_adjacent_typo(char: str) -> bool:
    """Hit a neighbouring key, notice, backspace, retype."""
    typo_char = _pick_typo_char(char)
    if not typo_char:
        return False

    _keyboard.press(typo_char)
    _keyboard.release(typo_char)
    time.sleep(random.uniform(0.200, 0.400))

    _keyboard.press(Key.backspace)
    _keyboard.release(Key.backspace)
    time.sleep(random.uniform(0.100, 0.200))
    return True


def _inject_double_tap(char: str) -> bool:
    """Accidentally press the same key twice, notice, backspace."""
    _keyboard.press(char)
    _keyboard.release(char)
    time.sleep(random.uniform(0.200, 0.400))

    _keyboard.press(Key.backspace)
    _keyboard.release(Key.backspace)
    time.sleep(random.uniform(0.100, 0.200))
    return True


def _inject_transposition(char: str, next_char: str) -> bool:
    """Type two characters in the wrong order, then fix.

    Types next_char first (wrong), then char, then backspaces both
    and retypes char correctly. The caller types next_char afterward.
    Skips if both characters are identical (transposition would be invisible).
    """
    if char.lower() == next_char.lower():
        return False

    _keyboard.press(next_char)
    _keyboard.release(next_char)
    time.sleep(random.uniform(0.040, 0.080))

    _keyboard.press(char)
    _keyboard.release(char)
    time.sleep(random.uniform(0.250, 0.450))

    for _ in range(2):
        _keyboard.press(Key.backspace)
        _keyboard.release(Key.backspace)
        time.sleep(random.uniform(0.080, 0.150))

    time.sleep(random.uniform(0.100, 0.200))
    return True


def _try_inject_typo(char: str, next_char: str | None) -> bool:
    """Roll for a typo type and inject it.  Returns True if a typo occurred."""
    roll = random.random()
    if roll < 0.30 and next_char is not None:
        return _inject_transposition(char, next_char)
    if roll < 0.45:
        return _inject_double_tap(char)
    return _inject_adjacent_typo(char)


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

    turbo = config.turbo
    typo_count = 0
    max_typos = 2 if len(word) >= 10 else 1
    burst_counter = 0
    next_burst_at = random.randint(2, 6)
    prev_char: str | None = None

    for i, char in enumerate(word):
        if not state.is_active:
            return False
        if can_continue is not None and not can_continue():
            return False

        # Typos: never on the first or last character.
        if (
            not turbo
            and config.typo_enabled
            and typo_count < max_typos
            and 0 < i < len(word) - 1
            and random.random() < config.typo_probability
        ):
            next_char = word[i + 1] if i + 1 < len(word) - 1 else None
            if _try_inject_typo(char, next_char):
                typo_count += 1

        _keyboard.press(char)
        _keyboard.release(char)

        if not turbo:
            delay = _sample_delay(config)
            delay += _hand_transition_delay(prev_char, char)
            burst_counter += 1
            if burst_counter >= next_burst_at:
                delay += random.uniform(0.040, 0.150)
                burst_counter = 0
                next_burst_at = random.randint(2, 6)
            time.sleep(delay)

        prev_char = char

    if not state.is_active:
        return False
    if can_continue is not None and not can_continue():
        return False

    if not turbo:
        time.sleep(random.uniform(0.040, 0.120))
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    return True
