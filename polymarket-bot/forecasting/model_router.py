"""
Tiered LLM model routing.
Tracks per-minute and per-day request counts for OpenRouter free tier.
Falls back to NVIDIA NIM on daily limit hit.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes LLM tasks to appropriate tier:
    - Tier 1 (FREE): OpenRouter free tier or NVIDIA NIM or local Ollama
    - Tier 2 (PAID): Anthropic Claude Sonnet (direct SDK) or DeepSeek R1 via OpenRouter
    """

    def __init__(self) -> None:
        self._cfg = settings.model
        self._openai_client = None
        self._anthropic_client = None
        self._nvidia_client = None
        self._ollama_client = None

        # Rate limiting state for OpenRouter free tier
        self._openrouter_minute_timestamps: deque[float] = deque()
        self._openrouter_daily_count: int = 0
        self._openrouter_daily_reset: float = time.time() + 86400
        self._using_nvidia_fallback: bool = False

    # ------------------------------------------------------------------
    # Client factories
    # ------------------------------------------------------------------

    def _get_openrouter_client(self):
        if self._openai_client is None:
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(
                api_key=self._cfg.openrouter_api_key,
                base_url=self._cfg.openrouter_base_url,
                default_headers={
                    "HTTP-Referer": "https://github.com/polymarket-bot",
                    "X-Title": "Polymarket Geo Bot",
                },
            )
        return self._openai_client

    def _get_nvidia_client(self):
        if self._nvidia_client is None:
            from openai import AsyncOpenAI
            self._nvidia_client = AsyncOpenAI(
                api_key=self._cfg.nvidia_api_key,
                base_url=self._cfg.nvidia_nim_base_url,
            )
        return self._nvidia_client

    def _get_ollama_client(self):
        if self._ollama_client is None:
            from openai import AsyncOpenAI
            self._ollama_client = AsyncOpenAI(
                api_key="ollama",
                base_url=self._cfg.ollama_base_url,
            )
        return self._ollama_client

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(
                api_key=self._cfg.anthropic_api_key,
            )
        return self._anthropic_client

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_openrouter_rate_limit(self) -> bool:
        """Returns True if within limits, False if daily limit exceeded."""
        now = time.time()

        # Reset daily counter
        if now >= self._openrouter_daily_reset:
            self._openrouter_daily_count = 0
            self._openrouter_daily_reset = now + 86400
            self._using_nvidia_fallback = False

        # Daily limit
        if self._openrouter_daily_count >= self._cfg.openrouter_max_rpd:
            if not self._using_nvidia_fallback:
                logger.warning(
                    "OpenRouter daily limit (%d req) reached — switching to NVIDIA NIM fallback",
                    self._cfg.openrouter_max_rpd,
                )
                self._using_nvidia_fallback = True
            return False

        # Per-minute limit: remove timestamps older than 60s
        cutoff = now - 60
        while self._openrouter_minute_timestamps and self._openrouter_minute_timestamps[0] < cutoff:
            self._openrouter_minute_timestamps.popleft()

        return len(self._openrouter_minute_timestamps) < self._cfg.openrouter_max_rpm

    async def _wait_for_rate_limit(self) -> None:
        """Wait until a free-tier request slot is available (per-minute limit)."""
        for attempt in range(30):  # Max 5 minutes of waiting
            now = time.time()
            cutoff = now - 60
            while self._openrouter_minute_timestamps and self._openrouter_minute_timestamps[0] < cutoff:
                self._openrouter_minute_timestamps.popleft()

            if len(self._openrouter_minute_timestamps) < self._cfg.openrouter_max_rpm:
                self._openrouter_minute_timestamps.append(now)
                self._openrouter_daily_count += 1
                return

            wait = 60 - (now - self._openrouter_minute_timestamps[0]) + 1
            logger.debug("Rate limit: waiting %.1fs for next slot", wait)
            await asyncio.sleep(wait)

        raise RuntimeError("Could not acquire OpenRouter rate limit slot after 5 minutes")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call_free(self, messages: list[dict], max_tokens: int = 2000) -> str:
        """
        Route to the cheapest/free model.
        Priority: Ollama (local) → OpenRouter free tier → NVIDIA NIM fallback.
        """
        if self._cfg.use_local_ollama:
            return await self._call_ollama(messages, max_tokens)

        within_openrouter_limits = self._check_openrouter_rate_limit()

        if within_openrouter_limits:
            await self._wait_for_rate_limit()
            return await self._call_openrouter_free(messages, max_tokens)
        else:
            return await self._call_nvidia_nim(messages, max_tokens)

    async def call_paid(self, messages: list[dict], max_tokens: int = 2000) -> str:
        """
        Route to the frontier paid model (Claude Sonnet via Anthropic SDK).
        Falls back to DeepSeek R1 via OpenRouter if Anthropic key unavailable.
        """
        if self._cfg.anthropic_api_key:
            return await self._call_anthropic(messages, max_tokens)
        elif self._cfg.openrouter_api_key:
            logger.warning("No Anthropic key — using paid tier via OpenRouter")
            return await self._call_openrouter_paid(messages, max_tokens)
        else:
            raise RuntimeError("No API key available for paid model. Set ANTHROPIC_API_KEY in .env")

    # ------------------------------------------------------------------
    # Internal call implementations
    # ------------------------------------------------------------------

    async def _call_openrouter_free(self, messages: list[dict], max_tokens: int) -> str:
        client = self._get_openrouter_client()
        response = await client.chat.completions.create(
            model=self._cfg.free_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    async def _call_openrouter_paid(self, messages: list[dict], max_tokens: int) -> str:
        client = self._get_openrouter_client()
        # Use a paid DeepSeek R1 model as OpenRouter alternative
        model = "deepseek/deepseek-r1" if "deepseek" in self._cfg.paid_model.lower() else self._cfg.paid_model
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    async def _call_anthropic(self, messages: list[dict], max_tokens: int) -> str:
        client = self._get_anthropic_client()
        # Convert OpenAI-style messages to Anthropic format
        system_content = None
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                anthropic_messages.append({"role": msg["role"], "content": msg["content"]})

        kwargs: dict[str, Any] = {
            "model": self._cfg.paid_model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
            "temperature": 0.2,
        }
        if system_content:
            kwargs["system"] = system_content

        response = await client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

    async def _call_nvidia_nim(self, messages: list[dict], max_tokens: int) -> str:
        client = self._get_nvidia_client()
        if not self._cfg.nvidia_api_key:
            logger.warning("No NVIDIA API key — returning empty response")
            return ""
        # NVIDIA NIM uses Llama models with same OpenAI interface
        response = await client.chat.completions.create(
            model="meta/llama-3.3-70b-instruct",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    async def _call_ollama(self, messages: list[dict], max_tokens: int) -> str:
        client = self._get_ollama_client()
        response = await client.chat.completions.create(
            model="llama3.3",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
