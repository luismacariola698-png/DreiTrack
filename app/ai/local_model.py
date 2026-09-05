from typing import Any

import httpx

from app.ai.config import (
    get_ai_model,
    get_ai_timeout,
    get_ollama_url,
)


# =========================================================
# LOCAL AI ERRORS
# =========================================================

class LocalAIError(Exception):
    """
    Base exception for local AI failures.
    """


class LocalAIUnavailableError(
    LocalAIError
):
    """
    Ollama could not be reached.
    """


class LocalAIModelMissingError(
    LocalAIError
):
    """
    Ollama is running, but DreiTrack's
    configured model is unavailable.
    """


class LocalAIResponseError(
    LocalAIError
):
    """
    Ollama returned an unusable response.
    """


# =========================================================
# RESPONSE CLEANING
# =========================================================

def clean_ai_response(
    text: str,
) -> str:
    """
    Clean formatting that DreiTrack does not support.

    Drei responses are displayed as plain text,
    so Markdown formatting markers should not
    appear in the user interface.
    """

    cleaned = text.strip()


    # Remove Markdown bold markers.
    #
    # Example:
    #
    # **Sample Joint Motor**
    #
    # becomes:
    #
    # Sample Joint Motor

    cleaned = cleaned.replace(
        "**",
        "",
    )


    # Remove Markdown code fences.

    cleaned = cleaned.replace(
        "```",
        "",
    )


    return cleaned.strip()


# =========================================================
# STATUS CHECK
# =========================================================

def get_local_ai_status() -> dict[str, Any]:
    """
    Check whether Ollama is available and whether
    DreiTrack's configured AI model is installed.
    """

    base_url = get_ollama_url()

    model_name = get_ai_model()


    try:

        response = httpx.get(
            f"{base_url}/api/tags",
            timeout=5.0,
        )

        response.raise_for_status()


    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.HTTPError,
    ):

        return {
            "available": False,
            "server_available": False,
            "model_available": False,
            "model": model_name,
            "message": (
                "The local Ollama service "
                "is not available."
            ),
        }


    try:

        data = response.json()

    except ValueError:

        return {
            "available": False,
            "server_available": True,
            "model_available": False,
            "model": model_name,
            "message": (
                "Ollama returned an invalid "
                "status response."
            ),
        }


    installed_models = {
        model.get("name")
        for model in data.get(
            "models",
            []
        )
        if model.get("name")
    }


    model_available = (
        model_name in installed_models
    )


    if not model_available:

        return {
            "available": False,
            "server_available": True,
            "model_available": False,
            "model": model_name,
            "message": (
                f"The model '{model_name}' "
                "is not installed."
            ),
        }


    return {
        "available": True,
        "server_available": True,
        "model_available": True,
        "model": model_name,
        "message": (
            "DreiTrack local AI is available."
        ),
    }


# =========================================================
# CHAT
# =========================================================

def chat_with_local_model(
    messages: list[dict[str, str]],
) -> str:
    """
    Send a conversation to Drei through Ollama.

    This function handles communication with
    the local AI service and ensures responses
    are safe for DreiTrack's plain-text interface.
    """

    if not messages:

        raise ValueError(
            "At least one message is required."
        )


    base_url = get_ollama_url()

    model_name = get_ai_model()


    payload = {
        "model":
            model_name,

        "messages":
            messages,

        "stream":
            False,

        "think":
            False,

        "keep_alive":
            "10m",
    }


    try:

        response = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=get_ai_timeout(),
        )


    except (
        httpx.ConnectError,
        httpx.TimeoutException,
    ) as exc:

        raise LocalAIUnavailableError(
            "The local AI service could not be reached."
        ) from exc


    if response.status_code == 404:

        raise LocalAIModelMissingError(
            (
                "The configured DreiTrack AI model "
                f"'{model_name}' is unavailable."
            )
        )


    try:

        response.raise_for_status()

    except httpx.HTTPStatusError as exc:

        raise LocalAIResponseError(
            (
                "The local AI service returned "
                f"HTTP {response.status_code}."
            )
        ) from exc


    try:

        data = response.json()

    except ValueError as exc:

        raise LocalAIResponseError(
            "The local AI service returned invalid JSON."
        ) from exc


    message = data.get(
        "message"
    )


    if not isinstance(
        message,
        dict,
    ):

        raise LocalAIResponseError(
            "The local AI response did not contain a message."
        )


    content = message.get(
        "content"
    )


    if not isinstance(
        content,
        str,
    ):

        raise LocalAIResponseError(
            "The local AI response did not contain text."
        )


    content = clean_ai_response(
        content
    )


    if not content:

        raise LocalAIResponseError(
            "Drei returned an empty response."
        )


    return content