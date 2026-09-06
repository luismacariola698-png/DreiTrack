import os

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_AI_MODEL = "dreitrack-ai:1.0"
DEFAULT_AI_TIMEOUT_SECONDS = 90.0


def get_ollama_url() -> str:
    return os.getenv("DREITRACK_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")


def get_ai_model() -> str:
    return os.getenv("DREITRACK_AI_MODEL", DEFAULT_AI_MODEL)


def get_ai_timeout() -> float:
    try:
        timeout = float(os.getenv("DREITRACK_AI_TIMEOUT_SECONDS", DEFAULT_AI_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_AI_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_AI_TIMEOUT_SECONDS
