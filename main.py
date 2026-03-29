"""JKLM BombParty Bot entry point."""

from __future__ import annotations

import random
import sys
import time
from collections import deque
from typing import Final, Optional

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
from translations import get_messages
from typing_simulation import type_word
from window_manager import (
    get_foreground_window,
    get_window_region,
    is_window_focused,
)
from word_engine import WordIndex, load_dictionary, score_and_rank

# Main loop polling intervals.
POLL_INTERVAL: Final[float] = 0.005
IDLE_SLEEP: Final[float] = 0.05
PRE_TYPE_DELAY_MIN: Final[float] = 0.05
PRE_TYPE_DELAY_MAX: Final[float] = 0.15
_UI_SETTLE_MS: Final[float] = 0.040
POST_TYPE_SETTLE: Final[float] = 0.85
POST_TYPE_SETTLE_TURBO: Final[float] = 0.40
_RAPID_POLL_INTERVAL: Final[float] = 0.008
_ACCEPTED_THRESHOLD: Final[float] = 0.85


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


def _underline_syllable(word: str, syllable: str) -> str:
    """Underline the target syllable in the word using ANSI codes."""
    if not word or not syllable:
        return word
    target = syllable.lower()
    replacement = f"\033[4m{target}\033[0m"
    return word.lower().replace(target, replacement, 1)


class BotRunner:
    """Encapsulates the BombParty bot state and main event loop."""

    def __init__(self, config: BotConfig, argv: list[str] | None = None) -> None:
        self.config = config
        self.msg = get_messages(config.language)

        dictionary = load_dictionary(config.wordlist_path)
        self.word_index = WordIndex(dictionary)
        warmup_ocr()

        _log(self.msg.loaded_words.format(count=f"{len(dictionary):,}"))

        self.state = GameState(life_letters=get_life_letters(config.language))
        if config.turbo:
            self.state.debounce_frames = 1

        self.game_window: gw.Win32Window | None = None
        self.locked_title: str = ""
        self.region: Optional[tuple[int, int, int, int]] = None
        self.was_focused = True

        self.turn_handled = False
        self.was_my_turn = False
        self.played_count_at_turn_start = 0
        self.round_reset_logged = False
        self.last_expired_syllable: str | None = None

        self.toggle_key = _hotkey_str_to_key(config.toggle_hotkey)
        self.user_input_buffer: list[str] = []

    def run(self) -> None:
        """Attach keyboard listeners and run the synchronous main loop."""
        listener = keyboard.Listener(on_press=self._on_key_press)
        listener.daemon = True
        listener.start()

        _log(self.msg.press_to_toggle.format(key=self.config.toggle_hotkey.upper()))

        try:
            self._main_loop()
        except KeyboardInterrupt:
            _log(self.msg.exiting)
            sys.exit(0)

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == self.toggle_key:
            if not self.state.autoplay:
                try:
                    self.game_window = get_foreground_window()
                    self.region = get_window_region(self.game_window)
                    self.locked_title = self.game_window.title
                    self.was_focused = True
                    if not self.state.is_active:
                        self.state.is_active = True
                        self.state.reset_round()
                    self.state.autoplay = True
                    _log(self.msg.enabled_on)
                except (RuntimeError, ValueError) as exc:
                    _log(self.msg.error.format(detail=exc))
            else:
                self.state.autoplay = False
                _log(self.msg.disabled)
            return

        if (
            not self.state.is_active
            or not self.state.is_my_turn
            or self.state.autoplay
            or not self.was_focused
        ):
            return

        if hasattr(key, "char") and key.char and key.char.isalpha():
            self.user_input_buffer.append(key.char)
        elif key == keyboard.Key.backspace:
            if self.user_input_buffer:
                self.user_input_buffer.pop()
        elif key in (keyboard.Key.space, keyboard.Key.esc):
            self.user_input_buffer.clear()
        elif key == keyboard.Key.enter:
            word = "".join(self.user_input_buffer).lower()
            if word:
                self.state.human_submitted_word = word
            self.user_input_buffer.clear()

    def _main_loop(self) -> None:
        while True:
            if (
                not self.state.is_active
                or self.game_window is None
                or self.region is None
            ):
                time.sleep(IDLE_SLEEP)
                continue

            if not self._check_window_focus():
                time.sleep(IDLE_SLEEP)
                continue

            if not self._update_window_region():
                continue

            try:
                roi_arr = capture_input_roi(self.region)
            except (ValueError, mss.exception.ScreenShotError):
                time.sleep(0.5)
                continue

            self.state.update_turn(detect_turn_active_from_array(roi_arr))

            if self._check_round_restart(roi_arr):
                time.sleep(POLL_INTERVAL)
                continue

            if self._check_turn_expiration():
                time.sleep(POLL_INTERVAL)
                continue

            turn_is_fresh = self._initialize_new_turn()

            if not self.state.turn_just_started and self.turn_handled:
                if not self.state.autoplay and self.state.human_submitted_word:
                    pass
                else:
                    time.sleep(POLL_INTERVAL)
                    continue

            if not self._wait_for_ui_settle(turn_is_fresh):
                continue

            if not self._read_and_evaluate_syllable():
                time.sleep(POLL_INTERVAL)
                continue

            self.turn_handled = True

            if self.state.autoplay:
                force_reset = self._process_active_turn()
            else:
                force_reset = self._process_human_turn()

            if force_reset or not _is_turn_active(self.region):
                self.state.reset_turn_tracking()
                self.turn_handled = False
            else:
                self.turn_handled = False

    def _check_window_focus(self) -> bool:
        focused = is_window_focused(self.game_window)
        if focused:
            try:
                focused = self.game_window.title == self.locked_title
            except (AttributeError, RuntimeError, OSError):
                focused = False

        if not focused:
            if self.was_focused:
                if self.state.autoplay:
                    _log(self.msg.paused)
                self.was_focused = False
                self.user_input_buffer.clear()
            return False

        if not self.was_focused:
            if self.state.autoplay:
                _log(self.msg.resumed)
            self.was_focused = True

        return True

    def _update_window_region(self) -> bool:
        try:
            self.region = get_window_region(self.game_window)
            return True
        except (RuntimeError, gw.PyGetWindowException, OSError) as exc:
            _log(self.msg.window_lost.format(detail=exc))
            self.state.is_active = False
            self.game_window = None
            self.region = None
            return False

    def _check_round_restart(self, roi_arr: mss.tools.np.ndarray) -> bool:
        if detect_round_restart(roi_arr):
            if not self.round_reset_logged:
                if self.was_my_turn and self.state.current_syllable:
                    if (
                        self.state.successful_plays_count
                        == self.played_count_at_turn_start
                    ):
                        if self.state.current_syllable != self.last_expired_syllable:
                            if self.state.autoplay and not self.state.surrendered_turn:
                                _log(
                                    self.msg.expired_for.format(
                                        syllable=self.state.current_syllable
                                    )
                                )
                if (
                    len(self.state.played_words) > 0
                    or self.state.successful_plays_count > 0
                ):
                    _log(self.msg.game_ended)
                self.state.reset_round()
                self.was_my_turn = False
                self.turn_handled = False
                self.round_reset_logged = True
                self.last_expired_syllable = None
            return True
        self.round_reset_logged = False
        return False

    def _check_turn_expiration(self) -> bool:
        if not self.state.is_my_turn:
            if self.was_my_turn and self.state.current_syllable:
                if self.state.successful_plays_count == self.played_count_at_turn_start:
                    if self.state.current_syllable != self.last_expired_syllable:
                        if self.state.autoplay and not self.state.surrendered_turn:
                            _log(
                                self.msg.expired_for.format(
                                    syllable=self.state.current_syllable
                                )
                            )
                        self.last_expired_syllable = self.state.current_syllable
                self.state.current_syllable = None
            self.was_my_turn = False
            self.turn_handled = False
            return True
        return False

    def _initialize_new_turn(self) -> bool:
        if not self.was_my_turn:
            self.was_my_turn = True
            self.played_count_at_turn_start = self.state.successful_plays_count
            return True
        return False

    def _wait_for_ui_settle(self, turn_is_fresh: bool) -> bool:
        if not self.config.turbo:
            time.sleep(random.uniform(PRE_TYPE_DELAY_MIN, PRE_TYPE_DELAY_MAX))
            if not self.state.is_active or not is_window_focused(self.game_window):
                return False
        elif turn_is_fresh or self.state.turn_just_started:
            time.sleep(_UI_SETTLE_MS)
        return True

    def _read_and_evaluate_syllable(self) -> bool:
        if self.state.autoplay or not self.state.current_syllable:
            syllable = read_syllable_from_region(self.region)
            if not syllable:
                return False

            if syllable != self.state.current_syllable:
                self.state.current_syllable = syllable
                self.state.candidate_queue.clear()

            if not self.state.candidate_queue and self.state.autoplay:
                return not self._evaluate_fallbacks(syllable)
        return True

    def _evaluate_fallbacks(self, syllable: str) -> bool:
        """Evaluate and inject candidates. Return True if queue is empty (fallback executed)."""
        self.state.candidate_queue = deque(
            score_and_rank(
                self.word_index.find(syllable, self.state.played_words),
                self.state.unused_letters,
                letter_rarity=self.word_index.letter_rarity,
                syllable=syllable,
            )
        )
        if not self.state.candidate_queue:
            _log(self.msg.no_match.format(syllable=syllable))
            if random.random() < 0.75:
                try:
                    click_input_field(self.region)
                except (RuntimeError, ValueError):
                    pass
                type_word(
                    "/suicide",
                    self.config,
                    self.state,
                    can_continue=lambda: self.state.is_active,
                )
            self.state.surrendered_turn = True
            self.turn_handled = True
            return True
        return False

    def _can_continue_typing(self) -> bool:
        if (
            not self.state.autoplay
            or not self.state.is_active
            or not is_window_focused(self.game_window)
        ):
            return False
        try:
            if self.game_window.title != self.locked_title:
                return False
        except (AttributeError, RuntimeError, OSError):
            return False
        return _is_turn_active(self.region)

    def _process_active_turn(self) -> bool:
        """Process an autoplay turn iteratively pulling candidates. Returns True if turn ends natively."""
        syllable = self.state.current_syllable
        while self.state.candidate_queue:
            if not _is_turn_active(self.region):
                return True

            word = self.state.candidate_queue.popleft()
            if self.state.is_blocked(word):
                self.state.played_words.add(word.lower())
                continue

            try:
                click_input_field(self.region)
                if not self.config.turbo:
                    time.sleep(0.02)
            except (RuntimeError, ValueError):
                pass

            completed = type_word(
                word, self.config, self.state, can_continue=self._can_continue_typing
            )
            if not completed:
                return True

            settle = POST_TYPE_SETTLE_TURBO if self.config.turbo else POST_TYPE_SETTLE
            submit_time = time.monotonic()
            turn_ended = False

            while time.monotonic() - submit_time < settle:
                if not _is_turn_active(self.region):
                    turn_ended = True
                    break
                time.sleep(_RAPID_POLL_INTERVAL)

            if turn_ended:
                elapsed = time.monotonic() - submit_time
                if elapsed < _ACCEPTED_THRESHOLD:
                    self.state.mark_word_played(word)
                    _log(
                        self.msg.played_for.format(
                            word=_underline_syllable(word, syllable), syllable=syllable
                        )
                    )
                else:
                    self.state.played_words.add(word.lower())
                    _log(self.msg.expired_for.format(syllable=syllable))
                return True

            current = read_syllable_from_region(self.region)

            if current is None:
                if not _is_turn_active(self.region):
                    self.state.mark_word_played(word)
                    _log(
                        self.msg.played_for.format(
                            word=_underline_syllable(word, syllable), syllable=syllable
                        )
                    )
                    return True
                self.state.mark_word_rejected(word)
                _log(
                    self.msg.rejected_for.format(
                        word=_underline_syllable(word, syllable), syllable=syllable
                    )
                )
            elif current != syllable:
                self.state.mark_word_rejected(word)
                _log(
                    self.msg.rejected_for.format(
                        word=_underline_syllable(word, syllable), syllable=syllable
                    )
                )
                self.state.candidate_queue.clear()
                return True
            else:
                self.state.mark_word_rejected(word)
                _log(self.msg.rejected_for.format(word=word, syllable=syllable))

            if not self.state.candidate_queue:
                self._evaluate_fallbacks(syllable)
                if not self.state.candidate_queue:
                    return True

        return False

    def _process_human_turn(self) -> bool:
        """Process human input words. Returns True to force loop reset."""
        word = self.state.human_submitted_word
        if not word:
            self.turn_handled = False
            self.state.candidate_queue.clear()
            time.sleep(POLL_INTERVAL)
            return False

        self.state.human_submitted_word = None
        submit_time = time.monotonic()
        turn_ended = False

        while time.monotonic() - submit_time < POST_TYPE_SETTLE:
            if not _is_turn_active(self.region):
                turn_ended = True
                break
            time.sleep(_RAPID_POLL_INTERVAL)

        if turn_ended:
            self.state.mark_word_played(word)
        else:
            current = read_syllable_from_region(self.region)
            if current and current != self.state.current_syllable:
                self.state.mark_word_played(word)
                self.state.current_syllable = current
            else:
                self.state.mark_word_rejected(word)

        self.user_input_buffer.clear()
        return True


def main(argv: list[str] | None = None) -> None:
    """Run the BombParty bot main loop."""
    config = load_config(argv)
    bot = BotRunner(config, argv)
    bot.run()


if __name__ == "__main__":
    main()
