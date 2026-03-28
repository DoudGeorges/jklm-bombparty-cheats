"""JKLM BombParty Bot entry point."""

from __future__ import annotations

import random
import sys
import time
from collections import deque
from typing import Final

import mss
import pygetwindow as gw
from pynput import keyboard

from config import BotConfig, load_config
from game_state import GameState, get_life_letters
from screen_reader import (
    capture_input_roi,
    click_input_field,
    detect_round_restart,
    detect_turn_active_from_array,
    read_syllable_from_region,
    warmup_ocr,
)
from translations import Messages, get_messages
from typing_simulation import type_word
from window_manager import (
    get_foreground_window,
    get_window_region,
    is_window_focused,
)
from word_engine import WordIndex, load_dictionary, score_and_rank

# Main loop polling intervals.
POLL_INTERVAL: Final[float] = 1.0 / 30
IDLE_SLEEP: Final[float] = 0.1

# Thinking time after reading the syllable.  The OCR processing
# (~100-200ms) already covers the visual recognition phase, so this
# only needs to cover the time a human would spend picking a word.
PRE_TYPE_DELAY_MIN: Final[float] = 0.05
PRE_TYPE_DELAY_MAX: Final[float] = 0.15

# Minimum wait before the first OCR read on a new turn.  The input bar
# color changes before the bomb circle text updates, so reading too
# early returns the previous turn's syllable.
_UI_SETTLE_MS: Final[float] = 0.040

# Wait for the game server to process a submitted word.
POST_TYPE_SETTLE: Final[float] = 0.30
POST_TYPE_SETTLE_TURBO: Final[float] = 0.20

# Rapid polling interval during post-submit detection.  8ms ensures we
# catch even sub-33ms turn cycles against fast opponent bots.
_RAPID_POLL_INTERVAL: Final[float] = 0.008

# Time threshold to distinguish accepted words from bomb explosions.
# If the turn ends within this time after pressing Enter, the word was
# accepted.  If it takes longer, the bomb timer ran out.
_ACCEPTED_THRESHOLD: Final[float] = 0.20


def _log(msg: str) -> None:
    print(msg)


def _hotkey_str_to_key(hotkey: str) -> keyboard.Key | keyboard.KeyCode:
    """Convert a hotkey name (e.g. 'f8') to a pynput key constant."""
    key_attr = hotkey.lower()
    if hasattr(keyboard.Key, key_attr):
        return getattr(keyboard.Key, key_attr)
    if len(hotkey) == 1:
        return keyboard.KeyCode.from_char(hotkey)
    raise ValueError(f"Unknown hotkey: {hotkey!r}")


def _is_turn_active(region: tuple[int, int, int, int]) -> bool:
    """Fast turn-active check using only the input-field ROI."""
    try:
        roi = capture_input_roi(region)
        return detect_turn_active_from_array(roi)
    except (ValueError, mss.exception.ScreenShotError):
        return False


def _attempt_candidates(
    *,
    syllable: str,
    config: BotConfig,
    state: GameState,
    word_index: WordIndex,
    region: tuple[int, int, int, int],
    game_window: gw.Win32Window,
    locked_title: str,
    msg: Messages,
) -> None:
    """Try each queued candidate word until the turn ends or the queue is exhausted.

    On each iteration:
      1. Bail if the turn ended (pixel check).
      2. Click the input field, type the word, press Enter.
      3. Rapid-poll the input bar to detect turn end:
         - Turn ended quickly  → word accepted.
         - Turn ended slowly   → bomb exploded.
         - Turn still active   → re-read syllable to distinguish
           rejection from a fast opponent cycle.
    """

    def _can_continue() -> bool:
        if not state.is_active:
            return False
        if not is_window_focused(game_window):
            return False
        try:
            return bool(game_window.title == locked_title)
        except (AttributeError, RuntimeError, OSError):
            return False

    while state.candidate_queue:
        if not _is_turn_active(region):
            break

        word = state.candidate_queue.popleft()
        if state.is_blocked(word):
            state.played_words.add(word.lower())
            continue

        try:
            click_input_field(region)
            if not config.turbo:
                time.sleep(0.02)
        except (RuntimeError, ValueError):
            pass

        completed = type_word(word, config, state, can_continue=_can_continue)
        if not completed:
            break

        # Rapid-poll at 8ms to catch even sub-33ms turn transitions
        # (critical against fast opponent bots).
        settle = POST_TYPE_SETTLE_TURBO if config.turbo else POST_TYPE_SETTLE
        submit_time = time.monotonic()
        turn_ended = False

        while time.monotonic() - submit_time < settle:
            if not _is_turn_active(region):
                turn_ended = True
                break
            time.sleep(_RAPID_POLL_INTERVAL)

        if turn_ended:
            elapsed = time.monotonic() - submit_time
            if elapsed < _ACCEPTED_THRESHOLD:
                state.mark_word_played(word)
                _log(msg.played_for.format(word=word, syllable=syllable))
            else:
                state.played_words.add(word.lower())
                _log(msg.expired_for.format(syllable=syllable))
            break

        # Turn still active after settle.  Usually means rejection, but
        # a fast opponent could have completed an entire cycle within the
        # settle window.  Re-read syllable to distinguish.
        current = read_syllable_from_region(region)

        if current is None:
            # OCR failed or turn ended while reading.
            if not _is_turn_active(region):
                state.mark_word_played(word)
                _log(msg.played_for.format(word=word, syllable=syllable))
                break
            state.mark_word_rejected(word)
            _log(msg.rejected_for.format(word=word, syllable=syllable))
        elif current != syllable:
            # Syllable changed — word went through, fast opponent already
            # answered, turn returned to us with a new syllable.
            state.mark_word_played(word)
            _log(msg.played_for.format(word=word, syllable=syllable))
            state.current_syllable = current
            state.candidate_queue.clear()
            break
        else:
            state.mark_word_rejected(word)
            _log(msg.rejected_for.format(word=word, syllable=syllable))

        if not state.candidate_queue:
            state.candidate_queue = deque(score_and_rank(
                word_index.find(syllable, state.played_words),
                state.unused_letters,
                letter_rarity=word_index.letter_rarity,
            ))


def main(argv: list[str] | None = None) -> None:
    """Run the BombParty bot main loop."""
    config = load_config(argv)
    msg = get_messages(config.language)

    dictionary = load_dictionary(config.wordlist_path)
    word_index = WordIndex(dictionary)
    warmup_ocr()

    _log(msg.loaded_words.format(count=f"{len(dictionary):,}"))

    state = GameState(life_letters=get_life_letters(config.language))
    if config.turbo:
        state.debounce_frames = 1
    was_focused = True

    game_window: gw.Win32Window | None = None
    locked_title: str = ""
    region: tuple[int, int, int, int] | None = None
    turn_handled = False
    was_my_turn = False
    played_count_at_turn_start = 0
    round_reset_logged = False

    toggle_key = _hotkey_str_to_key(config.toggle_hotkey)

    def _on_key_press(key: keyboard.Key | keyboard.KeyCode) -> None:
        nonlocal game_window, locked_title, region, was_focused
        if key != toggle_key:
            return
        if not state.is_active:
            try:
                game_window = get_foreground_window()
                region = get_window_region(game_window)
                locked_title = game_window.title
                was_focused = True
                state.is_active = True
                state.reset_round()
                _log(msg.enabled_on.format(
                    title=locked_title,
                    size=f"{region[2]}x{region[3]}",
                ))
            except (RuntimeError, ValueError) as exc:
                _log(msg.error.format(detail=exc))
        else:
            state.is_active = False
            _log(msg.disabled)

    listener = keyboard.Listener(on_press=_on_key_press)
    listener.daemon = True
    listener.start()

    _log(msg.press_to_toggle.format(key=config.toggle_hotkey.upper()))

    try:
        while True:
            if not state.is_active or game_window is None or region is None:
                time.sleep(IDLE_SLEEP)
                continue

            focused = is_window_focused(game_window)
            if focused:
                try:
                    focused = game_window.title == locked_title
                except (AttributeError, RuntimeError, OSError):
                    focused = False
            if not focused:
                if was_focused:
                    _log(msg.paused)
                    was_focused = False
                time.sleep(IDLE_SLEEP)
                continue
            if not was_focused:
                _log(msg.resumed)
                was_focused = True

            try:
                region = get_window_region(game_window)
            except RuntimeError as exc:
                _log(msg.window_lost.format(detail=exc))
                state.is_active = False
                game_window = None
                region = None
                continue

            try:
                roi_arr = capture_input_roi(region)
            except (ValueError, mss.exception.ScreenShotError):
                time.sleep(0.5)
                continue

            state.update_turn(detect_turn_active_from_array(roi_arr))

            # Green button visible = game ended / new round.
            if detect_round_restart(roi_arr):
                if not round_reset_logged:
                    state.reset_round()
                    was_my_turn = False
                    turn_handled = False
                    round_reset_logged = True
                    _log(msg.game_ended)
                time.sleep(POLL_INTERVAL)
                continue
            round_reset_logged = False

            if not state.is_my_turn:
                if was_my_turn and state.current_syllable:
                    if len(state.played_words) == played_count_at_turn_start:
                        _log(msg.expired_for.format(syllable=state.current_syllable))
                    state.current_syllable = None
                was_my_turn = False
                turn_handled = False
                time.sleep(POLL_INTERVAL)
                continue

            if not was_my_turn:
                was_my_turn = True
                turn_is_fresh = True
                played_count_at_turn_start = len(state.played_words)
            else:
                turn_is_fresh = False

            if not state.turn_just_started and turn_handled:
                time.sleep(POLL_INTERVAL)
                continue

            # UI settle: give the bomb circle time to render the new
            # syllable.  Normal mode's pre-type delay already covers
            # this; turbo mode needs an explicit wait on fresh turns.
            if not config.turbo:
                time.sleep(random.uniform(PRE_TYPE_DELAY_MIN, PRE_TYPE_DELAY_MAX))
                if not state.is_active or not is_window_focused(game_window):
                    continue
            elif turn_is_fresh or state.turn_just_started:
                time.sleep(_UI_SETTLE_MS)

            syllable = read_syllable_from_region(region)
            if not syllable:
                time.sleep(POLL_INTERVAL)
                continue

            if syllable != state.current_syllable:
                state.current_syllable = syllable
                state.candidate_queue.clear()

            if not state.candidate_queue:
                state.candidate_queue = deque(score_and_rank(
                    word_index.find(syllable, state.played_words),
                    state.unused_letters,
                    letter_rarity=word_index.letter_rarity,
                ))
                if not state.candidate_queue:
                    _log(msg.no_match.format(syllable=syllable))
                    turn_handled = True
                    continue

            turn_handled = True

            _attempt_candidates(
                syllable=syllable,
                config=config,
                state=state,
                word_index=word_index,
                region=region,
                game_window=game_window,
                locked_title=locked_title,
                msg=msg,
            )

            # Force re-debounce if the turn actually ended.
            if not _is_turn_active(region):
                state.reset_turn_tracking()
                turn_handled = False
            else:
                turn_handled = True
            state.candidate_queue.clear()
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        _log(msg.exiting)
        sys.exit(0)


if __name__ == "__main__":
    main()
