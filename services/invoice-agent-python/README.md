## Invoice Agent Service (LangGraph skeleton)

Servicio Python independiente para el agente de QA sobre facturas.

Objetivo:
- Exponer un endpoint HTTP (`POST /ask`) que use LangGraph como orquestador.
- Usar Groq vía SDK oficial de OpenAI.
- Hablar con el MCP server de facturas (Node/TS) para acceder a SQLite.

Estado actual:
- Solo estructura inicial de carpetas y módulos.
- Sin lógica de LangGraph implementada todavía.

Estructura propuesta:
- `src/main.py` – FastAPI app mínima y wiring básico.
- `src/agent/state.py` – definición de `InvoiceAgentState`.
- `src/agent/graph.py` – definición del grafo LangGraph.
- `src/agent/nodes/` – nodos del grafo (por ahora stubs).
- `src/services/openai_client.py` – cliente Groq/OpenAI.
- `src/services/mcp_client.py` – cliente hacia el MCP de facturas.
- `src/config.py` – configuración del servicio (env vars, etc.).

