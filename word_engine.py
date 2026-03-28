"""Dictionary loading, substring indexing, and weighted-score ranking."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Final

__all__ = ["WordIndex", "load_dictionary", "score_and_rank"]

_MIN_WORD_LENGTH: Final[int] = 2
_MAX_SYLLABLE_LEN: Final[int] = 5

# Scoring weights — tuned for BombParty strategic optimality.
_W_LIFE: Final[float] = 15.0
_W_UNUSED: Final[float] = 5.0
_W_RARITY: Final[float] = 3.0
_W_EFFICIENCY: Final[float] = 8.0
_W_LENGTH: Final[float] = 0.5

# When remaining life letters drop to this threshold or below, the urgency
# multiplier kicks in to aggressively target those specific letters.
_LIFE_URGENCY_THRESHOLD: Final[int] = 5


class WordIndex:
    """Pre-built substring index for O(1) candidate lookup.

    Computes per-letter scarcity weights from the loaded dictionary
    so the scoring algorithm can prioritise clearing rare letters.
    """

    __slots__ = ("_index", "_words", "_letter_rarity")

    def __init__(self, words: list[str]) -> None:
        self._words = words
        self._index: dict[str, set[str]] = defaultdict(set)
        letter_word_counts: dict[str, int] = defaultdict(int)

        for word in words:
            wl = len(word)
            word_chars = set(word)
            for ch in word_chars:
                letter_word_counts[ch] += 1
            for sub_len in range(2, min(_MAX_SYLLABLE_LEN, wl) + 1):
                for start in range(wl - sub_len + 1):
                    self._index[word[start : start + sub_len]].add(word)

        # Rarity = log(total / count).  Letters in fewer words get a
        # higher weight, incentivising the bot to clear them early.
        total = max(len(words), 1)
        self._letter_rarity: dict[str, float] = {
            ch: math.log(total / max(count, 1))
            for ch, count in letter_word_counts.items()
        }

    def __len__(self) -> int:
        return len(self._words)

    def __repr__(self) -> str:
        return f"WordIndex({len(self._words)} words, {len(self._index)} substrings)"

    @property
    def letter_rarity(self) -> dict[str, float]:
        """Per-letter scarcity weights (higher = rarer in dictionary)."""
        return self._letter_rarity

    def find(self, syllable: str, played_words: set[str]) -> list[str]:
        """Return words containing *syllable* that haven't been played yet."""
        key = syllable.lower()
        candidates = self._index.get(key)
        if candidates is None:
            return []
        return [w for w in candidates if w not in played_words]


def load_dictionary(path: Path) -> list[str]:
    """Load a word list file.  Returns lowercase alpha-only words of length >= 2.

    Raises:
        FileNotFoundError: If the word list file does not exist.
        OSError: If the file cannot be read (permissions, encoding, etc.).
    """
    if not path.exists():
        raise FileNotFoundError(f"Word list not found: {path}")

    words: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                word = line.strip().lower()
                if len(word) >= _MIN_WORD_LENGTH and word.isalpha():
                    words.append(word)
    except OSError as exc:
        raise OSError(f"Failed to read word list {path}: {exc}") from exc
    return words


def score_and_rank(
    candidates: list[str],
    unused_letters: set[str],
    letter_rarity: dict[str, float] | None = None,
) -> list[str]:
    """Rank candidates using a weighted multi-factor scoring model.

    Scoring factors:

      1. **Life-letter coverage** — Letters contributing toward earning
         an extra life.  Weight increases exponentially as the player
         approaches a full alphabet clear (adaptive urgency).

      2. **Unused-letter coverage** — Raw count of unused letters cleared.

      3. **Rarity bonus** — When ``letter_rarity`` is provided, unused
         letters appearing in fewer dictionary words receive higher
         weight, ensuring hard-to-clear letters are targeted early.

      4. **Coverage efficiency** — Ratio of unused letters cleared to
         word length.  Shorter words clearing many letters score higher.

      5. **Length shaping** — When letters still need clearing, a log
         penalty favours shorter words.  When all are covered, a bell
         curve around 4-7 characters keeps picks reliable and fast.

    Returns:
        Candidates sorted best-first.
    """
    if not candidates:
        return []

    unused_lower = {ch.lower() for ch in unused_letters}

    # Adaptive urgency: as the player gets closer to earning a life, the
    # per-letter payoff becomes exponentially more valuable.
    life_urgency = 1.0
    if unused_lower:
        remaining = len(unused_lower)
        if remaining <= _LIFE_URGENCY_THRESHOLD:
            life_urgency = _LIFE_URGENCY_THRESHOLD / max(remaining, 1)

    all_covered = not unused_lower

    def _score(word: str) -> float:
        wlen = len(word)
        if wlen == 0:
            return float("-inf")

        word_chars = set(word)

        if all_covered:
            # All letters covered: optimise for speed + reliability.
            # Bell curve peaks at length 5, falls off for very short
            # (often invalid) and very long (slow to type) words.
            ideal_len = 5.0
            return -((wlen - ideal_len) ** 2) * 0.1

        life_covered = len(word_chars & unused_lower)
        life_score = life_covered * _W_LIFE * life_urgency

        unused_covered = word_chars & unused_lower
        unused_count = len(unused_covered)
        unused_score = unused_count * _W_UNUSED

        if letter_rarity and unused_covered:
            rarity_sum = sum(
                letter_rarity.get(ch, 0.0) for ch in unused_covered
            )
            unused_score += rarity_sum * _W_RARITY

        efficiency_score = (unused_count / wlen) * _W_EFFICIENCY

        length_penalty = math.log1p(wlen) * _W_LENGTH

        return life_score + unused_score + efficiency_score - length_penalty

    return sorted(candidates, key=_score, reverse=True)
