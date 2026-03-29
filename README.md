# JKLM BombParty Bot

An intelligent auto-typer built for the [jklm.fun BombParty](https://jklm.fun/) web game. It uses computer vision and optical character recognition (OCR) to identify active syllables directly from the screen, and then simulates human typing to play the game automatically.

## Features

- **Computer Vision OCR**: The bot identifies active syllables by reading the screen natively, utilizing [mss](https://github.com/BoboTiG/python-mss) for ultra-fast screen capture and [EasyOCR](https://github.com/JaidedAI/EasyOCR) for highly precise text recognition.
- **Dictionary Optimization Engine**: A specialized scoring model selects candidate words. This engine optimizes clearing unused alphabet letters while balancing for acceptable word lengths.
- **Multilingual Support**: Operations are actively supported across four languages: English, French, German, and Spanish.
- **Human-Like Character Input**: To simulate a natural typing cadence, the bot introduces variance within configured Words Per Minute (WPM) bounds, calculates keyboard layout transition delays, and organically injects (and auto-corrects) common typographical errors.
- **Resilient Fallbacks**: If the vocabulary is exhausted mid-turn, the bot autonomously detects the unplayable state and gracefully triggers a lobby "/suicide" command to yield the turn immediately.
- **Turbo Mode**: An optional, zero-delay configuration that bypasses all simulated timing restraints, forcing keystrokes at the absolute maximum speed permissible by the operating system.

## Setup Requirements

Python 3.12+ is required. Deploying within a dedicated virtual environment is strongly recommended to cleanly manage the machine-learning and imaging dependencies.

1. Clone the repository and navigate into the directory:
   ```bash
   git clone https://github.com/DoudGeorges/jklm-bombparty-cheats.git
   cd jklm-bombparty-cheats
   ```

2. Install dependencies (`uv` is recommended for lightning-fast environment resolution):
   ```bash
   uv pip install -r requirements.txt
   ```

Note: The optical character recognition engine utilizes [PyTorch](https://pytorch.org/). If the host machine runs an NVIDIA GPU, verify that the active Python environment is properly configured for CUDA compatibility to minimize CPU overhead.

## Execution

Start the script via the command line interface while the jklm.fun lobby is visible on the primary monitor.

Default execution (English vocabulary):
```bash
python main.py
```

Execute with a specific language code (fr, de, es):
```bash
python main.py --language fr
```

Execute with Turbo Mode enabled:
```bash
python main.py --turbo
```

The `F8` key serves as the global toggle. Once switched on, continuous screen analysis begins. As soon as an active game turn is detected, candidate selection and automated typing start immediately.

## Advanced Configuration

Internal variables, such as the hardware toggle key, algorithmic WPM bounds, or typo induction probabilities, can be modified by creating a `config.json` file in the root directory:

```json
{
  "language": "en",
  "toggle_hotkey": "f8",
  "window_title": "jklm.fun",
  "typing_wpm_range": [100, 130],
  "typo_enabled": true,
  "typo_probability": 0.04,
  "turbo": false
}
```

## Disclaimer

This source code is provided strictly for educational purposes, dictionary logic analysis, and isolated application testing. All interactions with public lobbies must strictly comply with relevant community guidelines and server terms of service.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
