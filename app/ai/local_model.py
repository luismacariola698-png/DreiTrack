from typing import Any

import httpx

from app.ai.config import get_ai_model, get_ai_timeout, get_ollama_url


class LocalAIError(Exception):
    """Base exception for local AI failures."""


class LocalAIUnavailableError(LocalAIError):
    """Ollama could not be reached."""


class LocalAIModelMissingError(LocalAIError):
    """The configured model is unavailable."""


class LocalAIResponseError(LocalAIError):
    """Ollama returned an unusable response."""


def clean_ai_response(text: str) -> str:
    return text.strip().replace("**", "").replace("```", "").strip()


def _status(model: str, *, server: bool, available: bool, message: str) -> dict[str, Any]:
    return {
        "available": available,
        "server_available": server,
        "model_available": available,
        "model": model,
        "message": message,
    }


def get_local_ai_status() -> dict[str, Any]:
    base_url, model_name = get_ollama_url(), get_ai_model()
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        response.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
        return _status(model_name, server=False, available=False, message="The local Ollama service is not available.")

    try:
        installed = {m.get("name") for m in response.json().get("models", []) if m.get("name")}
    except ValueError:
        return _status(model_name, server=True, available=False, message="Ollama returned an invalid status response.")

    if model_name not in installed:
        return _status(model_name, server=True, available=False, message=f"The model '{model_name}' is not installed.")
    return _status(model_name, server=True, available=True, message="DreiTrack local AI is available.")


def chat_with_local_model(messages: list[dict[str, str]]) -> str:
    if not messages:
        raise ValueError("At least one message is required.")

    base_url, model_name = get_ollama_url(), get_ai_model()
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
    }
    try:
        response = httpx.post(f"{base_url}/api/chat", json=payload, timeout=get_ai_timeout())
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise LocalAIUnavailableError("The local AI service could not be reached.") from exc

    if response.status_code == 404:
        raise LocalAIModelMissingError(f"The configured DreiTrack AI model '{model_name}' is unavailable.")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LocalAIResponseError(f"The local AI service returned HTTP {response.status_code}.") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise LocalAIResponseError("The local AI service returned invalid JSON.") from exc

    message = data.get("message")
    if not isinstance(message, dict):
        raise LocalAIResponseError("The local AI response did not contain a message.")
    content = message.get("content")
    if not isinstance(content, str):
        raise LocalAIResponseError("The local AI response did not contain text.")
    content = clean_ai_response(content)
    if not content:
        raise LocalAIResponseError("Drei returned an empty response.")
    return content
