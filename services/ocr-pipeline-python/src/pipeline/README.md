Módulo Pipeline
===============

Resumen
-------
- Pipeline de OCR + LLM de extremo a extremo para extraer datos estructurados de facturas (esquema invoice_v1) desde PDFs e imágenes.
- Pasos: subida → hash para caché → detección de fuente → extracción de texto → construcción de prompts → LLM → parseo → normalización/clasificación/validación → persistencia + caché.
- Diseñado como componentes pequeños y testeables, con un orquestador delgado y una capa de compatibilidad para imports legacy.

Flujo
-----
1. Calcular hash (SHA‑256) y consultar la caché.
2. Detectar la fuente: PDF vs imagen.
3. Extraer texto: pdfminer (estructurado) y, si la señal es débil, fallback a OCR con Tesseract (DPI configurable).
4. Construir prompts (system + user) con esquema estricto y manejo de formatos numéricos europeos.
5. Llamar a la API de Chat Completions de Groq con limitación de tasa.
6. Parsear el JSON y construir `InvoiceV1`.
7. Normalizar totales, inferir/ajustar valores, unir líneas descriptivas, clasificar ítems, armonizar escalas de montos, recomputar descuento y validar campos requeridos.
8. Persistir JSON y tablas estructuradas en SQLite y devolver resultado en caché para archivos idénticos.

Módulos y responsabilidades
---------------------------
- service/orchestrator.py
  - Punto de entrada `run_pipeline(path: str) -> dict` que coordina todo el flujo.
  - Gestiona caché, detección de fuente, extracción, llamada al LLM, parseo, normalización, validación y persistencia.
- service/pipeline.py
  - Capa de compatibilidad que reexporta `run_pipeline`. Las importaciones existentes `from ...service.pipeline import run_pipeline` siguen funcionando.
- service/normalizer.py
  - Corrige errores comunes de montos del LLM (4 patrones), armoniza escalas, recomputa descuentos y extrae valores del resumen desde texto OCR.
  - Provee `apply_summary_overrides()` (actualmente deshabilitado en el orquestador por formatos europeos con miles espaciados como `1 054,10`).
- service/item_processor.py
  - Une líneas descriptivas al ítem anterior, filtra ítems que son solo de resumen (ej. descuento/envío), valida totales por ítem y filtra falsos positivos en warnings.
- service/validators.py
  - Valida campos requeridos y formato de fecha; helpers de texto para compactar prompt y presupuesto dinámico de tokens.
- extract/text_extractor.py
  - Extracción unificada para PDF/imagen. Usa primero pdfminer y cae a OCR (Tesseract) si hace falta. El DPI se configura con `PDF_OCR_DPI`.
  - Provee `PageText` y `join_pages()`.
- ingest/loader.py
  - Detecta tipo de archivo (PDF vs imagen) por extensión/MIME.
- llm/prompts.py
  - Construye prompts estrictos con snippet de esquema, lista de categorías y reglas para formatos europeos, mapeo del resumen y líneas descriptivas.
- llm/groq_client.py
  - Llama a Groq Chat Completions con reintentos y limitador de tasa consciente de tokens. Soporta respuestas stub si falta la API key.
- llm/validator.py
  - Acepta respuestas solo JSON (recortando code fences) y valida contra `InvoiceV1`.
- llm/rate_limiter.py
  - Limitador thread‑safe para RPM/RPD/TPM/TPD con estadísticas por tag.
- schema/invoice_v1.py
  - Modelos Pydantic: `Invoice`, `Item`, `Notes`, `InvoiceV1`.
- storage/db.py
  - Modelos y helpers de SQLAlchemy. Persiste JSON crudo y tablas estructuradas de factura/ítems. Caché por hash SHA‑256.
- utils/files.py
  - Hash SHA‑256 en streaming para claves de caché.
- config/settings.py
  - Carga `.env` y resuelve paths y settings usados en el pipeline (directorios, URL/path de DB, OCR/LLM, rate limits, umbrales).

Configuración
-------------
- LLM
  - `PIPELINE_LLM_API_BASE` / `GROQ_API_BASE` (por defecto `https://api.groq.com/openai/v1`)
  - `PIPELINE_LLM_API_KEY` / `GROQ_API_KEY`
  - `PIPELINE_LLM_MODEL` (por defecto `llama-3.3-70b-versatile`)
  - `PIPELINE_LLM_ALLOW_STUB` (`true` habilita respuestas stub sin red)
- OCR
  - `PDF_OCR_DPI` (por defecto 300), `PDF_OCR_MAX_PAGES` (por defecto 5)
  - `TEXT_MIN_LENGTH` umbral mínimo para considerar la extracción válida
- Almacenamiento/Paths
  - `DB_URL` o `DB_PATH` (SQLite), `UPLOAD_DIR`, `PROCESSED_DIR`, `SAMPLES_DIR`

Decisiones de diseño
--------------------
- Moneda: `resolve_currency()` actualmente devuelve `USD` por defecto. Extender si se requiere detección multi‑moneda.
- Overrides de resumen: deshabilitadas por defecto debido a formatos europeos con miles espaciados. Rehabilitar en el orquestador cuando el parseo sea robusto para casos como `"1 054,10"`.
- Envíos/cargos: tratados como adiciones y mapeados a `tax_cents` para cumplir `total = subtotal + adiciones - descuento`.
- Caché: deduplicación por SHA‑256 evita llamadas repetidas al LLM para archivos idénticos.

Uso del pipeline
----------------
- Import recomendado:
  - `from src.pipeline.service.orchestrator import run_pipeline`
- Import legacy (seguro):
  - `from src.pipeline.service.pipeline import run_pipeline`
- Invocar `run_pipeline("/ruta/absoluta/al/archivo.pdf")` y recibir un `dict` compatible con `InvoiceV1`.

Extensibilidad
--------------
- Categorías: ajustar keywords/pistas en `category/rules.py`.
- Normalización: agregar nuevos patrones o reglas en `service/normalizer.py`.
- Prompts: refinar instrucciones del LLM en `llm/prompts.py`.
- Persistencia: cambiar la base ajustando `DB_URL` en config.

Estado de código legacy/no usado
--------------------------------
- No quedan módulos legacy bajo `service/` tras el refactor; `service/pipeline.py` existe solo como shim de compatibilidad.
- `apply_summary_overrides()` existe pero está deshabilitada intencionalmente en el orquestador por riesgos conocidos del parseo OCR; mantener para una futura activación.
