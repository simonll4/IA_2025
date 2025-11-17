from pydantic import BaseSettings


class Settings(BaseSettings):
    """Configuración básica del servicio de Invoice Agent."""

    api_host: str = "0.0.0.0"
    api_port: int = 8100

    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"

    mcp_endpoint: str = "http://localhost:8200"

    class Config:
        env_prefix = "INVOICE_AGENT_"
        case_sensitive = False


settings = Settings()

