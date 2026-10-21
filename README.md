# ARCEUS Alpha v0.1

> **A beginner-friendly Python conversational assistant for Windows 11.**

ARCEUS Alpha is a modular, extensible chatbot framework built with clean
separation of concerns. It ships with three model backends — a local **echo**
mode for offline/testing, **OpenAI** for cloud AI, and **Ollama** for local
LLMs — and can be extended with new backends in a few lines of code.

---

## ✨ Features

| Feature | Status |
|---|---|
| Interactive CLI chat loop | ✅ |
| Pluggable AI backends (Echo / OpenAI / Ollama) | ✅ |
| Layered configuration (defaults → env vars → JSON file) | ✅ |
| Custom exception hierarchy with helpful messages | ✅ |
| Conversation history with automatic trimming | ✅ |
| Unit test suite (pytest) | ✅ |
| Voice / TTS | 🔜 Planned |
| Desktop automation | 🔜 Planned |
| Robotics integration | 🔜 Planned |

---

## 📁 Project Structure

```
arceus-alpha/
├── main.py                  # CLI entry-point (REPL)
├── requirements.txt         # Python dependencies
├── .gitignore               # Safe defaults for Python + Windows
│
├── arceus/                  # Core package
│   ├── __init__.py          # Version & metadata
│   ├── assistant.py         # Conversation engine
│   ├── config.py            # Layered configuration
│   ├── exceptions.py        # Custom error hierarchy
│   ├── model_interface.py   # Abstract + concrete AI backends
│   └── utils.py             # Logging, banner, input sanitisation
│
└── tests/                   # Unit tests (pytest)
    ├── test_assistant.py
    ├── test_config.py
    ├── test_exceptions.py
    ├── test_model_interface.py
    └── test_utils.py
```

---

## 🚀 Quick Start

### 1. Clone & set up a virtual environment

```powershell
cd arceus-alpha
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Run in echo mode (no API key needed)

```powershell
python main.py
```

### 3. Run with OpenAI

Create a `.env` file in the project root:

```env
ARCEUS_MODEL_BACKEND=openai
ARCEUS_OPENAI_API_KEY=sk-...
```

Then:

```powershell
python main.py --backend openai
```

### 4. Run with a local Ollama model

Make sure Ollama is running (`ollama serve`), then:

```powershell
python main.py --backend ollama
```

---

## ⚙️ Configuration

Configuration is resolved in this priority order:

1. **CLI flags** (`--backend`, `--config`)
2. **Environment variables** (prefix `ARCEUS_`, e.g. `ARCEUS_TEMPERATURE=0.5`)
3. **JSON config file** (`python main.py --config arceus_config.json`)
4. **Built-in defaults**

| Key | Default | Description |
|---|---|---|
| `model_backend` | `echo` | `echo`, `openai`, or `ollama` |
| `openai_api_key` | *(empty)* | Your OpenAI API key |
| `openai_model` | `gpt-3.5-turbo` | OpenAI model name |
| `ollama_host` | `http://localhost:11434` | Ollama server URL |
| `ollama_model` | `llama3` | Ollama model name |
| `system_prompt` | *"You are ARCEUS…"* | System prompt sent to the model |
| `max_history` | `50` | Max messages kept in context |
| `temperature` | `0.7` | Sampling temperature |
| `max_tokens` | `1024` | Max tokens per response |

---

## 🧪 Running Tests

```powershell
pytest tests/ -v
```

With coverage:

```powershell
pytest tests/ -v --cov=arceus --cov-report=term-missing
```

---

## 🛡️ Error Handling

All custom exceptions inherit from `ArceusError`, so you can catch
everything with a single `except ArceusError` or handle specific cases:

```
ArceusError
├── ConfigError
│   └── MissingAPIKeyError
├── ModelError
│   ├── ModelConnectionError
│   └── ModelResponseError
└── ConversationError
```

---

## 🔌 Adding a New Backend

1. Subclass `ModelInterface` in `arceus/model_interface.py`
2. Implement `generate(messages) -> str`
3. Register it in the `_BACKENDS` dict
4. Done — it's automatically available via `--backend yourname`

---

## 📝 License

MIT — use it, learn from it, build on it.
