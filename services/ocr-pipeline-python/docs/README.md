# OCR Pipeline Service

Servicio FastAPI que expone el pipeline OCR + LLM para extraer datos estructurados de facturas a partir de PDFs e imágenes. Esta app ya no incluye UI estática ni el asistente conversacional: el foco exclusivo es procesar documentos y entregar respuestas compatibles con el esquema `invoice_v1`.

## Capacidades principales
- Ingesta de PDF/PNG/JPG/BMP con validación de tipo y control de concurrencia.
- Extracción híbrida de texto (pdfminer ➜ Tesseract) con detección automática de fallback.
- Prompts estrictos para Groq/OpenAI compatibles y validación Pydantic del JSON devuelto.
- Normalización y clasificación de ítems + persistencia/caché en SQLite.
- API lista para Docker/Kubernetes, con healthcheck ligero.

## Estructura del proyecto
```
src/
  main.py                # Punto de entrada FastAPI (create_app)
  api/
    __init__.py
    health.py           # GET /api/health
    pipeline.py         # POST /api/pipeline/extract
  pipeline/             # Módulo del pipeline OCR/LLM
    config/             # settings.py y utilidades de paths/entorno
    ingest/, extract/   # Ingesta de archivos y OCR
    llm/                # Cliente Groq + rate limiter + prompts
    schema/             # Modelos invoice_v1
    service/            # Orchestrator + normalización + validadores
    storage/            # SQLAlchemy + caché
    utils/              # Helpers (hashes, etc.)
```
Otros archivos útiles:
- `requirements.txt`: dependencias mínimas del servicio.
- `docker-entrypoint.sh`: prepara permisos y directorios `/app/data`.
- `../../docker-compose.yml`: orquesta este servicio junto a otros microservicios.
- `../../clear_cache.py`: script CLI para limpiar la caché SQLite.

## Quickstart (Docker Compose)
```bash
cd pipeline-python
cp configs/env/.env.example configs/env/.env
# Ajusta PIPELINE_LLM_API_KEY antes de levantar
API_HOST_PORT=7001 docker compose up -d pipeline-api
```
- API: `http://localhost:7001`
- Health: `http://localhost:7001/api/health`

## Ejecución local (sin Docker)
```bash
cd services/ocr-pipeline-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp configs/env/.env.example configs/env/.env  # o apunta a ../../configs/env/.env
uvicorn src.main:app --reload --port 8000
```

## Consumir el pipeline vía API
```bash
curl -F file=@datasets/donut_samples/donut_train_0004.png   http://localhost:8000/api/pipeline/extract
```
Respuesta típica:
```json
{
  "schema_version": "invoice_v1",
  "invoice": {"vendor_name": "ACME", "total_cents": 12345, ...},
  "items": [ ... ],
  "notes": {"warnings": []}
}
```

## Consumir el pipeline desde Python
```python
from src.pipeline.service.pipeline import run_pipeline
from pprint import pprint

result = run_pipeline("datasets/donut_samples/donut_train_0004.png")
pprint(result)
```

## Variables de entorno relevantes
| Variable | Descripción | Default |
| --- | --- | --- |
| `PIPELINE_LLM_API_KEY` | API key de Groq/OpenAI. | `""` |
| `PIPELINE_LLM_API_BASE` | Endpoint compatible (Groq por defecto). | `https://api.groq.com/openai/v1` |
| `PIPELINE_LLM_MODEL` | Modelo usado para extracción. | `llama-3.3-70b-versatile` |
| `PIPELINE_LLM_ALLOW_STUB` | Devuelve stub si no hay API key. | `false` |
| `RATE_LIMIT_RPM/RPD` | Límites de requests por minuto/día. | `24 / 11500` |
| `RATE_LIMIT_TPM/TPD` | Límites de tokens por minuto/día. | `4800 / 400000` |
| `PDF_OCR_DPI` | DPI al rasterizar PDFs. | `300` |
| `PDF_OCR_MAX_PAGES` | Máximo de páginas a rasterizar. | `5` |
| `TEXT_MIN_LENGTH` | Caracteres mínimos tras OCR para omitir fallback. | `120` |
| `UPLOAD_DIR` | Carpeta de uploads temporales. | `data/uploads` |
| `PROCESSED_DIR` | Carpeta de exportaciones procesadas. | `data/processed` |
| `DB_URL` / `DB_PATH` | Cadena SQLite usada por SQLAlchemy. | `sqlite:///data/app.db` |
| `DB_DIR` | Carpeta raíz para la base si se arma automáticamente. | `data/` |
| `DEFAULT_CURRENCY` | Moneda fallback usada en normalización. | `UNK` |
| `MAX_CONCURRENCY` | Semáforo para limitar peticiones concurrentes. | `1` |

## Tips operativos
- Instala `poppler-utils` y `tesseract-ocr` (eng+spa) para ejecutar nativo.
- Usa `python clear_cache.py --all` cuando cambies prompts o lógica y necesites recalcular resultados.
- Ajusta `TEXT_MIN_LENGTH` si trabajas con tickets muy cortos.
- Para debugging es útil conservar los archivos subidos: desactiva el borrado en `api/pipeline.py` o copia `data/uploads`.

## Próximos pasos
- Añadir métricas/telemetría específicas del pipeline.
- Publicar imágenes Docker versionadas (tags semánticos).
- Integrar pruebas automatizadas por lote (`tests/test_ejes_batch.py`).
