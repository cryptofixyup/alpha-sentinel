"""Async, retry-aware labeling boundary.

The module is import-safe without an API key. Network calls happen only when
label_text is invoked, and credentials are read from the environment.
"""
from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))


def _client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for remote labeling")
    return AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT)


@retry(
    retry=retry_if_exception_type((TimeoutError, ConnectionError)),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
    stop=stop_after_attempt(_MAX_RETRIES),
    reraise=True,
)
async def _request_label(client: AsyncOpenAI, text: str) -> str:
    response = await client.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=16,
        messages=[
            {"role": "system", "content": "Return one concise security-relevant label."},
            {"role": "user", "content": text},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Model returned an empty label")
    return content.strip()


async def label_text(text: str, client: Optional[AsyncOpenAI] = None) -> str:
    """Label text using the configured model.

    A client may be injected for deterministic tests. No API credential is
    accepted as a function argument, preventing accidental credential logging
    or propagation through the data pipeline.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    owned_client = client is None
    active_client = client or _client()
    try:
        return await _request_label(active_client, text.strip())
    finally:
        if owned_client:
            await active_client.close()
