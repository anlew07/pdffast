# PDFFast v2 Architecture

PDFFast Core is a transport-agnostic PDF parser. The public boundary is
`PDFFastParser.parse(pdf_path)`, which returns artifact paths and structured
results. Core does not import FastAPI, UploadFile, HTTP request/response
objects, Celery, or any other service transport.

## Runtime flow

```text
PDF
  -> Stage 1-8 native analysis and quality gate
  -> Stage 9.1 fallback units
  -> Stage 9.2 capability routing
  -> Stage 9.6.3 frozen runtime policy
  -> Stage 9.8 Provider executor
       -> Provider Registry
       -> runtime normalizer
       -> selected prediction artifacts
  -> Stage 10.1 canonical document
  -> Stage 10.2 LLM-ready Markdown
  -> Stage 10.2.1 structure boundary audit
```

Provider adapters only execute one task and return `RawProviderResult`.
Escalation remains owned by the executor and frozen policy. The runtime
normalizer materializes that result in a run-local artifact directory before
calling the existing provider-specific canonical adapters; benchmark selection
and runtime enablement therefore remain separate concerns.

Workers for MinerU, Marker, and Docling run in their configured subprocess
environments. Their model caches are external to the repository and are used
offline when present.

## Service boundary

A future service adapter may call:

```python
result = parser.parse(pdf_path)
```

It may then map the result to HTTP or a queue protocol without changing the
pipeline, provider registry, or canonical contracts.
