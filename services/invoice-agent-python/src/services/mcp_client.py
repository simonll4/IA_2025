from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from ..config import settings


class MCPClient:
    """Cliente HTTP muy simple hacia el MCP de facturas (stub)."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or settings.mcp_endpoint

    def get_schema(self) -> Dict[str, Any]:
        """Stub para llamada a tool get_schema."""
        url = f"{self.base_url}/tools/get_schema"
        logger.debug(f"Calling MCP get_schema at {url}")
        # TODO: implementar contrato real cuando exista el server MCP.
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error calling MCP get_schema: {exc}")
            return {"error": str(exc)}

    def run_sql_select(self, query: str) -> Dict[str, Any]:
        """Stub para llamada a tool run_sql_select."""
        url = f"{self.base_url}/tools/run_sql_select"
        logger.debug(f"Calling MCP run_sql_select at {url}")
        payload = {"query": query}
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error calling MCP run_sql_select: {exc}")
            return {"error": str(exc)}


