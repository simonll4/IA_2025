/**
 * Skeleton de MCP server para dominio de facturas.
 *
 * Aquí se registrarán tools como:
 * - get_schema
 * - run_sql_select
 * y otras tools de dominio (get_invoice_summary, etc.).
 */

import path from "node:path";

import express from "express";

// TODO: importar e inicializar el SDK oficial de MCP cuando se integre.

const DB_PATH =
  process.env.APP_DB_PATH ??
  path.join(__dirname, "..", "..", "..", "data", "app.db");

const PORT = Number(process.env.MCP_HTTP_PORT ?? "3000");

const app = express();

app.use(express.json());

// Healthcheck simple
app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    service: "mcp-invoices-ts",
    dbPath: DB_PATH,
  });
});

// Stub de tool get_schema
app.get("/tools/get_schema", (_req, res) => {
  res.status(501).json({
    error: "NotImplemented",
    message: "Tool get_schema aún no está implementada",
  });
});

// Stub de tool run_sql_select
app.post("/tools/run_sql_select", (req, res) => {
  const { query } = req.body ?? {};
  res.status(501).json({
    error: "NotImplemented",
    message: "Tool run_sql_select aún no está implementada",
    receivedQuery: query ?? null,
  });
});

// Fallback 404
app.use((_req, res) => {
  res.status(404).json({ error: "NotFound" });
});

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(
    `[mcp-invoices-ts] Express MCP skeleton listening on port ${PORT}, DB_PATH=${DB_PATH}`,
  );
});
