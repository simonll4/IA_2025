"""FastAPI entrypoint for the OCR pipeline microservice."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health, pipeline


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    app = FastAPI(
        title="OCR Pipeline Service",
        description=(
            "HTTP API that exposes the OCR + LLM pipeline for structured invoice extraction"
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(pipeline.router)

    @app.get("/")
    async def root():  # pragma: no cover - simple info endpoint
        return {
            "service": "ocr-pipeline",
            "docs": "/docs",
            "endpoints": {
                "health": "/api/health",
                "extract": "/api/pipeline/extract",
            },
        }

    return app


app = create_app()


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
