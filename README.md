# 📄 Invoice Processing Platform

Plataforma simple para extraer datos estructurados de facturas usando OCR + LLM, expuesta vía una API HTTP. Incluye un módulo "assistant" para consultas conversacionales que está en desarrollo (versión básica inicial).

## Idea General

- Subes un PDF o imagen de una factura.
- Se extrae texto del documento:
  - PDFs: parsing con pdfminer.
  - Imágenes o PDFs con poco texto: OCR con Tesseract.
  - Luego se compacta preservando estructura útil.
- Un LLM interpreta el texto y genera un JSON con la factura (proveedor, fecha, importes, ítems, etc.).
- Se normaliza, valida y guarda en SQLite para consultas posteriores.

## Componentes

- Pipeline (estable): pdfminer para PDFs, OCR (Tesseract) para imágenes/fallback, prompts para LLM, normalización/validación y persistencia.
- Assistant (en desarrollo): consultas en lenguaje natural sobre las facturas ya procesadas. Estado: funcional básico.
- API HTTP (FastAPI) y una UI estática mínima para probar el flujo.

Organización orientada a servicios:

- `services/ocr-pipeline-python`: servicio actual de API unificada (pipeline + assistant) en FastAPI.
- `services/invoice-agent-python`: nuevo servicio independiente para el agente LangGraph (solo skeleton por ahora).
- `services/mcp-invoices-ts`: skeleton de MCP server en Node/TypeScript para acceso seguro a la DB SQLite.

## Inicio Rápido

1. Configurar variables (opcional):
   - `cp configs/env/.env.example configs/env/.env`
   - Si usas LLM remoto, define tu API key en `.env`.
2. Levantar el servicio:
   - `docker compose up -d`
3. Acceso:
   - UI: `http://localhost:7000`
   - Docs: `http://localhost:7000/docs`
   - Health: `http://localhost:7000/api/health`

## API mínima

- `POST /api/pipeline/extract` (multipart/form-data) con `file=<factura.pdf|.png|.jpg>`
  - Devuelve un JSON con la factura estructurada.
- `POST /api/assistant/chat` (experimental): consultas simples sobre datos ya cargados.

## Estado del proyecto

- Pipeline: listo para uso básico y pruebas con documentos reales.
- Assistant: MVP inicial; sujeto a cambios y mejoras.
