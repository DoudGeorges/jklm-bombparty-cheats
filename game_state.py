"""Stateful game tracker for BombParty rounds."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Final

__all__ = ["GameState", "LIFE_LETTERS_BY_LANG", "get_life_letters"]

LIFE_LETTERS_BY_LANG: dict[str, frozenset[str]] = {
    "en": frozenset("abcdefghijklmnopqrstuvwy"),  # no x, z
    "fr": frozenset("abcdefghijlmnopqrstuv"),  # no k, w, x, y, z
    "de": frozenset("abcdefghiklmnoprstuvwz"),  # no j, q, x, y
    "es": frozenset("abcdefghijlmnopqrstuv"),  # no k, w, x, y, z
}

_FALLBACK_LETTERS: Final[frozenset[str]] = frozenset("abcdefghijklmnopqrstuvwxyz")


def get_life_letters(language: str) -> frozenset[str]:
    """Return the life-letter set for a language code.

    Falls back to all 26 if the code is unknown.
    """
    return LIFE_LETTERS_BY_LANG.get(language, _FALLBACK_LETTERS)


DEFAULT_DEBOUNCE_FRAMES: Final[int] = 2

_STEM_MIN_LENGTH: Final[int] = 6


@dataclass
class GameState:
    """Track the current state of a BombParty game."""

    life_letters: frozenset[str] = field(
        default_factory=lambda: LIFE_LETTERS_BY_LANG["en"]
    )

    current_syllable: str | None = None
    played_words: set[str] = field(default_factory=set)
    is_my_turn: bool = False
    is_active: bool = False
    autoplay: bool = False
    successful_plays_count: int = 0
    human_submitted_word: str | None = None
    candidate_queue: deque[str] = field(default_factory=deque)

    debounce_frames: int = DEFAULT_DEBOUNCE_FRAMES
    _prev_is_my_turn: bool = False
    turn_just_started: bool = False
    _turn_on_count: int = 0

    letters_played_this_round: set[str] = field(default_factory=set)
    _rejected_stems: set[str] = field(default_factory=set)
    surrendered_turn: bool = False

    @property
    def unused_letters(self) -> frozenset[str]:
        """Letters still needed for an extra life."""
        return self.life_letters - self.letters_played_this_round

    def update_turn(self, raw_is_my_turn: bool) -> None:
        """Update turn state with debouncing."""
        if raw_is_my_turn:
            self._turn_on_count += 1
        else:
            self._turn_on_count = 0

        debounced_on = self._turn_on_count >= self.debounce_frames
        self.turn_just_started = debounced_on and not self._prev_is_my_turn
        self._prev_is_my_turn = debounced_on
        self.is_my_turn = debounced_on

    def mark_word_played(self, word: str) -> None:
        """Record a word as successfully played."""
        if not word:
            return
        lower = word.lower()
        self.played_words.add(lower)
        self.letters_played_this_round.update(lower)
        self.successful_plays_count += 1
        if not (self.life_letters - self.letters_played_this_round):
            self.letters_played_this_round.clear()

    def mark_word_rejected(self, word: str) -> None:
        """Exclude a rejected word and its base-root from future candidates."""
        if not word:
            return
        lower = word.lower()
        self.played_words.add(lower)

        base = lower
        for sfx in ("ing", "ed", "es", "s", "er", "ers", "ly", "man", "men"):
            if base.endswith(sfx) and len(base) > len(sfx) + 4:
                base = base[: -len(sfx)]
                if len(base) > 2 and base[-1] == base[-2]:
                    base = base[:-1]
                break

        if len(base) >= _STEM_MIN_LENGTH:
            self._rejected_stems.add(base)

    def is_blocked(self, word: str) -> bool:
        """Check if a candidate contains a previously rejected stem."""
        if not word or not self._rejected_stems:
            return False
        lower = word.lower()
        return any(stem in lower for stem in self._rejected_stems)

    def reset_turn_tracking(self) -> None:
        """Reset debounce counter for fresh re-detection on next poll."""
        self._turn_on_count = 0
        self._prev_is_my_turn = False
        self.turn_just_started = False
        self.is_my_turn = False
        self.surrendered_turn = False

    def reset_round(self) -> None:
        """Reset state for a new round."""
        self.played_words.clear()
        self.candidate_queue.clear()
        self.current_syllable = None
        self.letters_played_this_round.clear()
        self._rejected_stems.clear()
        self.successful_plays_count = 0
        self.surrendered_turn = False
