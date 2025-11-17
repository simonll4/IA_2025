"""
FastAPI app mínima para el servicio Invoice Agent.

Por ahora solo expone un endpoint de prueba y un stub de /ask.
La lógica real de LangGraph se implementará más adelante.
"""

from fastapi import FastAPI
from loguru import logger

from .config import settings

app = FastAPI(
    title="Invoice Agent Service",
    description="Servicio de agente para Q&A sobre facturas (LangGraph skeleton)",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "invoice-agent"}


@app.post("/ask")
async def ask(question: str) -> dict:
    """
    Endpoint stub para futuras preguntas al agente.

    De momento solo devuelve un mensaje fijo para no romper el contrato.
    """
    logger.info(f"Received question for agent (stub): {question}")
    return {
        "answer": "Invoice Agent todavía no está implementado. Aquí irá LangGraph.",
        "success": True,
    }


def run_dev() -> None:
    """Helper para levantar el servicio en desarrollo."""
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )

