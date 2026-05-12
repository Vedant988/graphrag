This folder contains a small pilot for the first 10 pages of `database/Mahabharata (Unabridged in English).pdf`.

It is meant to help you test three pipeline styles cheaply before attempting full ingestion:

1. `Simple LLM Q/A`
2. `Simple RAG`
3. `GraphRAG-style local pilot`

The pilot uses:

- Groq completion model: `openai/gpt-oss-120b`
- Gemini embeddings: `gemini-embedding-001`

Files:

- `run_pilot.py`: runs the 10-page pilot end to end
- `questions.json`: sample questions for the pilot, including benchmark metadata such as `favored_pipeline`, `benchmark_category`, and diagnosis notes
- `data/`: generated first-10-page assets
- `output/`: generated answers, graph artifacts, and usage logs

Run from the repo root:

```powershell
python tests/mahabharata_10_page_pilot/run_pilot.py
```

Optional flags:

```powershell
python tests/mahabharata_10_page_pilot/run_pilot.py --question-id sauti_role
python tests/mahabharata_10_page_pilot/run_pilot.py --max-pages 10 --chunk-size 6000 --chunk-overlap 400
```

Review notes from the repo code:

1. `graphrag/app/supportai/supportai_ingest.py` currently expects `document_er_extraction()` to return a dict with `nodes` and `rels`.
2. `common/extractors/LLMEntityRelationshipExtractor.py` actually returns a list of `GraphDocument` objects.
3. That mismatch is a risk for a direct reuse of `BatchIngestion._ingest()` as-is.
4. The pilot avoids that path and uses the repo prompt/schema for extraction while keeping the parsed graph locally in JSON/NetworkX.
5. The built-in ingestion flow also performs document-level extraction before chunk-level extraction. For very large PDFs that is expensive and likely to exceed context limits, so a chunk-first pilot is safer.
