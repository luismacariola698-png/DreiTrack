import os


# =========================================================
# LOCAL AI CONFIGURATION
# =========================================================

DEFAULT_OLLAMA_URL = (
    "http://127.0.0.1:11434"
)

DEFAULT_AI_MODEL = (
    "dreitrack-ai:1.0"
)

DEFAULT_AI_TIMEOUT_SECONDS = 90.0


def get_ollama_url() -> str:
    """
    Return the Ollama server used by DreiTrack.
    """

    value = os.getenv(
        "DREITRACK_OLLAMA_URL",
        DEFAULT_OLLAMA_URL,
    )

    return value.rstrip("/")


def get_ai_model() -> str:
    """
    Return the configured DreiTrack AI model.
    """

    return os.getenv(
        "DREITRACK_AI_MODEL",
        DEFAULT_AI_MODEL,
    )


def get_ai_timeout() -> float:
    """
    Return how long DreiTrack should wait
    for a local AI response.
    """

    raw_value = os.getenv(
        "DREITRACK_AI_TIMEOUT_SECONDS"
    )


    if raw_value is None:
        return DEFAULT_AI_TIMEOUT_SECONDS


    try:
        timeout = float(
            raw_value
        )

    except ValueError:
        return DEFAULT_AI_TIMEOUT_SECONDS


    if timeout <= 0:
        return DEFAULT_AI_TIMEOUT_SECONDS


    return timeout