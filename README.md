# JKLM BombParty Bot

A bot for [jklm.fun](https://jklm.fun/) BombParty that picks words to earn extra lives, types like a human, and supports multiple languages. Turbo mode strips all delays for unthrottled input.

The game is read through the screen using computer vision and OCR. Answers are typed through OS-level keystrokes. No browser access of any kind.

## Features

- **Smart word selection:** Picks words that clear life-letters toward earning extra lives, ranked by letter rarity, clearing efficiency, and syllable position. Priority escalates automatically as fewer life-letters remain.
- **Human-like typing:** Types within a configurable WPM range with natural timing variations and self-correcting typos.
- **Multilingual:** Supports English, French, Spanish, and German, each with a dedicated dictionary and a language-specific life-letter set.
- **Rejection recovery:** When a word is rejected, the next best candidate is submitted immediately without waiting for a new turn.
- **Screen-native OCR:** The active syllable is read directly from the screen via [EasyOCR](https://github.com/JaidedAI/EasyOCR). No page access required.
- **Auto-pause:** Pauses when the game window loses focus and resumes when it comes back.
- **Turbo mode:** Disables all timing simulation. Inputs fire at maximum OS speed.

## Setup

Python 3.12+ is required. A virtual environment is recommended.

1. Clone the repository:
   ```bash
   git clone https://github.com/DoudGeorges/jklm-bombparty-cheats.git
   cd jklm-bombparty-cheats
   ```

2. Install dependencies:
   ```bash
   uv pip install -r requirements.txt
   ```

> **Note:** EasyOCR requires [PyTorch](https://pytorch.org/). On NVIDIA hardware, CUDA is recommended. CPU inference is noticeably slower.

## Usage

```bash
# Default (English dictionary)
python main.py

# Language (fr, es, de)
python main.py --language fr

# Custom word list
python main.py --wordlist path/to/list.txt

# WPM range (default: 100 130)
python main.py --wpm 80 100

# Typo probability (default: 0.04)
python main.py --typo 0

# Turbo mode
python main.py --turbo

# Surrender probability (default: 0.5)
python main.py --surrender 0.8
```

Focus the game window, then press `F8` to enable the bot. It will start typing as soon as a turn is detected. Press `F8` again to stop at any time.

## Configuration

Place a `config.json` in the project root to override defaults. CLI flags take precedence over the file.

```json
{
  "language": "en",
  "hotkey": "f8",
  "wpm": [100, 130],
  "typo": 0.04,
  "turbo": false,
  "surrender": 0.5
}
```

| Key | Type | Default | CLI Flag | Description |
|---|---|---|---|---|
| `language` | string | `"en"` | `--language` / `-l` | Dictionary language (`en`, `fr`, `es`, `de`) |
| `hotkey` | string | `"f8"` | `--hotkey` / `-k` | Key that toggles the bot on and off |
| `wpm` | [int, int] | `[100, 130]` | `--wpm MIN MAX` | Typing speed range in WPM |
| `typo` | float | `0.04` | `--typo` | Per-keystroke typo probability |
| `turbo` | bool | `false` | `--turbo` / `-t` | Raw OS-speed input, bypassing `wpm` and `typo` |
| `surrender` | float | `0.5` | `--surrender` / `-s` | Probability of `/suicide` when no valid word is found |

## Disclaimer

This project is provided for educational purposes. Use in public lobbies must comply with relevant community guidelines and terms of service.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
