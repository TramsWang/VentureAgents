"""Minimal OpenAI API REPL using VentureAgents config.

Usage:
    python scripts/run_openai_call.py

Type a message and press Enter to send it to the configured chat model.
Use Ctrl-D/Ctrl-C, or type ``exit``/``quit``/``q`` to stop.

The script reads ``llm.openai`` and ``llm.chat`` settings from the project
config. Use an OpenAI Platform API key for the default OpenAI endpoint, or set
``llm.openai.base_url`` to the compatible provider that issued your key.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, AuthenticationError, OpenAIError

from venture_agents.utils.config import get_openai_api_key, get_settings


if TYPE_CHECKING:
    from venture_agents.schemas.config import ProjectSettings


EXIT_COMMANDS = {"exit", "quit", "q"}
SYSTEM_PROMPT = "You are a concise and helpful assistant."


def _response_value(value: object, key: str) -> object:
    """Read a value from OpenAI SDK objects or dict-like compatible responses."""
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _collect_text_parts(value: object) -> list[str]:
    """Collect text fields from common Responses API content shapes."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        parts: list[str] = []
        for item in value:
            parts.extend(_collect_text_parts(item))
        return parts

    text = _response_value(value, "text")
    if isinstance(text, str):
        return [text]
    return []


def _extract_response_text(response: object) -> str:
    """Extract generated text from Responses API responses."""
    output_text = _response_value(response, "output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = _response_value(response, "output")
    if isinstance(output, Sequence) and not isinstance(output, str | bytes):
        parts: list[str] = []
        for output_item in output:
            parts.extend(_collect_text_parts(_response_value(output_item, "content")))
            parts.extend(_collect_text_parts(_response_value(output_item, "text")))
        text = "".join(parts).strip()
        if text:
            return text

    return ""


def _create_client(settings: ProjectSettings) -> tuple[httpx.AsyncClient, AsyncOpenAI]:
    """Create an AsyncOpenAI client from project settings."""
    openai_settings = settings.llm.openai
    timeout = httpx.Timeout(openai_settings.timeout_seconds, read=openai_settings.read_timeout_seconds)
    http_client = httpx.AsyncClient(proxy=openai_settings.proxy, timeout=timeout)

    client_kwargs: dict[str, Any] = {
        "api_key": get_openai_api_key(),
        "http_client": http_client,
        "max_retries": openai_settings.max_retries,
    }
    if openai_settings.base_url is not None:
        client_kwargs["base_url"] = openai_settings.base_url
    if openai_settings.organization is not None:
        client_kwargs["organization"] = openai_settings.organization
    if openai_settings.project is not None:
        client_kwargs["project"] = openai_settings.project

    return http_client, AsyncOpenAI(**client_kwargs)


async def _ask_llm(client: AsyncOpenAI, settings: ProjectSettings, prompt: str) -> str:
    """Send one prompt to the configured chat model and return text output."""
    request_kwargs: dict[str, Any] = {
        "model": settings.llm.chat.model,
        "temperature": settings.llm.chat.temperature,
        "instructions": SYSTEM_PROMPT,
        "input": prompt,
    }
    if settings.llm.chat.max_tokens is not None:
        request_kwargs["max_output_tokens"] = settings.llm.chat.max_tokens

    response = await client.responses.create(**request_kwargs)
    text = _extract_response_text(response)
    if not text:
        msg = "OpenAI response did not contain generated text."
        raise RuntimeError(msg)
    return text


async def main() -> int:
    """Run a small stdin/stdout loop for testing the configured OpenAI API."""
    settings = get_settings()
    http_client, client = _create_client(settings)

    sys.stdout.write(f"OpenAI test REPL started. model={settings.llm.chat.model}\n")
    sys.stdout.write("Type exit/quit/q to stop.\n")

    try:
        while True:
            try:
                user_input = input("\nYou> ").strip()
            except EOFError:
                sys.stdout.write("\n")
                break

            if not user_input:
                continue
            if user_input.lower() in EXIT_COMMANDS:
                break

            try:
                response_text = await _ask_llm(client, settings, user_input)
            except AuthenticationError:
                sys.stderr.write(
                    "\nOpenAI authentication failed (HTTP 401).\n"
                    "Check llm.openai.api_key or OPENAI_API_KEY, and make sure "
                    "llm.openai.base_url matches the provider that issued the key.\n"
                )
                return 1
            except APIConnectionError:
                sys.stderr.write(
                    "\nCould not connect to the OpenAI API.\n"
                    "Check llm.openai.base_url, llm.openai.proxy, and your network connection.\n"
                )
                return 1
            except APIStatusError as exc:
                sys.stderr.write(f"\nOpenAI API request failed with HTTP {exc.status_code}.\n")
                return 1
            except OpenAIError as exc:
                sys.stderr.write(f"\nOpenAI API request failed: {exc.__class__.__name__}.\n")
                return 1

            sys.stdout.write(f"\nLLM> {response_text}\n")
            sys.stdout.flush()
    finally:
        await http_client.aclose()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        raise SystemExit(130) from None
