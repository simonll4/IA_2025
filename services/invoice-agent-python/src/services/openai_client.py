from typing import Any, Dict, List

from loguru import logger
from openai import OpenAI

from ..config import settings


def get_openai_client() -> OpenAI:
    """Devuelve un cliente OpenAI configurado para Groq."""
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY no configurada; el agente no podrá llamar al LLM")
    return OpenAI(base_url=settings.groq_base_url, api_key=settings.groq_api_key or "")


def simple_completion(prompt: str) -> str:
    """Helper mínimo para probar conectividad con Groq."""
    client = get_openai_client()
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


