# ARCEUS Voice Assistant v0.1

> **A beginner-friendly Python conversational & voice assistant for Windows 11.**

ARCEUS is a modular, privacy-first conversational assistant framework built with clean
separation of concerns. It supports both **Text Mode** (interactive REPL) and **Voice Mode** (speech-to-text, assistant reasoning, and speech synthesis).

It ships with three AI model backends — local **Echo** (offline testing), **OpenAI** (cloud LLM), and **Ollama** (local offline LLM) — and can be extended with new models or voice engines without rewriting application logic.

---

## ✨ Features

| Feature | Status | Details |
|---|---|---|
| Interactive CLI chat loop | ✅ | Full terminal text REPL |
| Interactive Voice conversation loop | ✅ | Push-to-talk (`--voice`), audio capture, STT, and TTS |
| Local AI Intelligence (Default) | ✅ | Powered by local Ollama `qwen2.5:3b` via `/api/generate` |
| 100% Local Offline TTS | ✅ | Powered by Windows 11 native voices via `pyttsx3` (0 MB model download) |
| Local Offline STT Option | ✅ | Powered by `vosk` (~45 MB lightweight local model) |
| Online STT Fallback | ✅ | Powered by `SpeechRecognition` (Google Web Speech API) |
| Pluggable AI backends | ✅ | `local` / `ollama` (default: `qwen2.5:3b`), `echo` (testing), `openai` |
| Layered configuration | ✅ | Defaults → `.env` / Env vars → JSON config → CLI flags |
| Custom exception hierarchy | ✅ | `ArceusError`, `AudioDeviceError`, `SpeechRecognitionError`, etc. |
| Comprehensive Unit Test Suite | ✅ | 86 unit tests with 100% mocked hardware & offline pass |
| Desktop automation | 🔜 Planned | Not implemented in v0.1 |
| Robotics integration | 🔜 Planned | Not implemented in v0.1 |

---

## 📁 Project Structure

```
arceus-alpha/
├── main.py                  # CLI entry-point (supports text REPL & --voice)
├── requirements.txt         # Python dependencies
├── .gitignore               # Safe defaults for Python + Windows
│
├── arceus/                  # Core package
│   ├── __init__.py          # Version & metadata
│   ├── assistant.py         # Conversation engine (history, trimming, reset)
│   ├── config.py            # Layered configuration & defaults
│   ├── exceptions.py        # Custom error hierarchy
│   ├── model_interface.py   # AI model backends (Echo, OpenAI, Ollama)
│   ├── utils.py             # Logging, banner, input sanitisation
│   │
│   └── voice/               # Voice subsystem
│       ├── __init__.py      # Subsystem exports
│       ├── audio_input.py   # Microphone recording via sounddevice (in-memory PCM)
│       ├── stt.py           # Speech-to-Text (Vosk offline & SpeechRecognition)
│       ├── tts.py           # Text-to-Speech (pyttsx3 Windows 11 SAPI5)
│       └── controller.py    # Voice conversation orchestrator
│
└── tests/                   # Unit tests (pytest)
    ├── test_assistant.py    # Assistant conversation engine tests
    ├── test_config.py       # Configuration resolution tests
    ├── test_exceptions.py   # Exception hierarchy tests
    ├── test_model_interface.py # Model backends & factory tests
    ├── test_utils.py        # Utility tests
    └── test_voice.py        # Complete mocked voice pipeline tests
```

---

## 🚀 Quick Start Guide (Windows 11)

### 1. Open PowerShell and navigate to the project

```powershell
cd "c:\Users\SOUMIK GHOSH\OneDrive\Desktop\arceus-alpha"
```

### 2. Activate the Virtual Environment

If using the existing `.venv`:
```powershell
.\.venv\Scripts\Activate.ps1
```

*(If script execution is disabled on your computer, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` first).*

### 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

---

## 🎙️ Using Voice Mode

### Launch Voice Mode (Uses Local Ollama `qwen2.5:3b` by default)

```powershell
python main.py --voice
```

Or for offline testing without Ollama:
```powershell
python main.py --voice --backend echo
```

### How the Voice Interaction Works

1. **Ready State**: ARCEUS indicates:
   ```
   [Ready to Listen] Press <Enter> to speak (or type 'exit' / 'quit' to leave):
   ```
2. **Explicit Trigger**: Press the **Enter** key when you are ready to talk. ARCEUS will never record in the background without your explicit action.
3. **Recording**: You will see:
   ```
   [Listening...] Please speak now (5s)...
   ```
   Speak clearly into your microphone.
4. **Transcription**:
   ```
   [Transcribing speech...]
   You (Voice) ➤ What is the speed of light?
   ```
5. **Assistant Response & Speech**:
   ```
   [Thinking...]
   ARCEUS ➤ The speed of light in a vacuum is approximately 299,792 kilometers per second.
   [Speaking response...]
   ```
   ARCEUS speaks the reply aloud through your default Windows audio device.
6. **Cycle Repeats**: You can continue speaking for multiple turns (2nd, 3rd, and beyond) in the same session.

### Exiting Voice Mode
You can exit at any time by:
- Typing `exit` or `quit` at the prompt.
- Saying `"quit"` or `"exit"` into your microphone.
- Pressing `Ctrl + C`.

---

## 💬 Using Text Mode

If you prefer typing, launch text mode without flags (uses local `qwen2.5:3b` by default):

```powershell
python main.py
```

Or choose an alternate backend:
```powershell
python main.py --backend echo      # Offline deterministic echo for testing
python main.py --backend openai    # Cloud OpenAI (needs ARCEUS_OPENAI_API_KEY)
```

---

## 🔒 Privacy & Safety Assessment

| Component | Network Connection | Where Audio Goes | Local / Offline |
|---|---|---|---|
| **Audio Capture** (`sounddevice`) | None | Kept in RAM as PCM WAV; automatically deleted | 100% Local |
| **Speech-to-Text (Vosk)** | None | Processed entirely on local CPU | 100% Offline |
| **Speech-to-Text (Google Fallback)** | Internet | Sends audio to Google Web Speech API | Cloud (Fallback) |
| **AI Assistant (Echo Mode)** | None | Stays on local computer | 100% Offline |
| **AI Assistant (Ollama)** | None (Localhost) | Stays on local computer (`localhost:11434`) | 100% Offline |
| **AI Assistant (OpenAI)** | Internet | Sends text prompt to OpenAI API | Cloud |
| **Text-to-Speech (`pyttsx3`)** | None | Synthesized via Windows 11 SAPI5 engine | 100% Offline |

> [!NOTE]
> For a **100% completely offline voice pipeline**, use **Echo** or **Ollama** as your AI backend and download the lightweight Vosk model. No data will ever leave your computer.

---

## 📦 Setting Up Speech Recognition Models

### Option A: Automatic Online Mode (Zero Download, Instant Testing)
By default, if no local Vosk model folder is found, ARCEUS uses the built-in `SpeechRecognition` Google speech recognizer. No setup or downloads are required.

### Option B: 100% Offline Vosk Model Setup
To enable completely offline speech recognition:
1. Download the lightweight English model (`vosk-model-small-en-us-0.15`, ~40 MB) from [Vosk Models](https://alphacephei.com/vosk/models).
2. Extract the folder into your project root as `model`:
   ```powershell
   # Example structure:
   arceus-alpha\model\
   ├── am\
   ├── conf\
   ├── graph\
   └── ivector\
   ```
3. ARCEUS will automatically detect this model on startup and run 100% offline!

---

## 🔊 Windows 11 Audio Configuration & Troubleshooting

### 1. Check Windows 11 Microphone Permissions
If you see `[Audio Error] No active microphone detected`:
1. Open **Windows 11 Settings** (`Win + I`).
2. Go to **Privacy & security** > **Microphone**.
3. Ensure **Microphone access** is toggled **ON**.
4. Ensure **Let desktop apps access your microphone** is toggled **ON**.

### 2. Verify Default Audio Devices
- Right-click the Speaker icon on your Windows 11 taskbar > **Sound settings**.
- Verify your active microphone is selected as the default input device.
- Verify your speakers or headphones are selected as the default output device.

---

## ⚙️ Configuration Reference

Settings can be specified in `.env`, environment variables with `ARCEUS_` prefix, or in a JSON config file:

| Key | Default | Description |
|---|---|---|
| `model_backend` | `local` | `local` (Ollama), `echo`, or `openai` |
| `openai_api_key` | *(empty)* | Your OpenAI API key |
| `openai_model` | `gpt-3.5-turbo` | OpenAI model name |
| `ollama_host` | `http://localhost:11434` | Ollama server URL |
| `ollama_model` | `qwen2.5:3b` | Ollama model name (uses `/api/generate`) |
| `system_prompt` | *"You are ARCEUS…"* | System prompt (concise 1-2 sentences) |
| `max_history` | `50` | Conversation context turns |
| `temperature` | `0.7` | Sampling temperature |
| `voice_record_timeout` | `5` | Recording duration in seconds |
| `voice_stt_engine` | `auto` | `auto`, `vosk`, or `google` |
| `voice_vosk_model_path` | `""` | Custom path to local Vosk model |
| `voice_tts_rate` | `180` | Speaking speed (words per minute) |
| `voice_tts_volume` | `1.0` | Output volume (`0.0` to `1.0`) |

---

## 🧪 Running Automated Tests

Run the full automated test suite:

```powershell
pytest tests/ -v
```

Run tests with code coverage:

```powershell
pytest tests/ -v --cov=arceus --cov-report=term-missing
```

> **Testing Guarantee**: All tests mock microphone input, speech recognition, and audio playback. No physical microphone, speakers, or internet connection are required to pass tests.

---

## 🛡️ Exception Hierarchy

All custom exceptions inherit from `ArceusError`:

```
ArceusError
├── ConfigError
│   └── MissingAPIKeyError
├── ModelError
│   ├── ModelConnectionError
│   └── ModelResponseError
├── ConversationError
└── VoiceError
    ├── AudioDeviceError
    ├── SpeechRecognitionError
    └── SpeechSynthesisError
```

---

## 📝 License

MIT — open-source, beginner-friendly, and extensible.
