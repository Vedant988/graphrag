# Friend Setup Guide

This guide is for a teammate cloning this repo on a fresh PC.

It is written for this repo's current setup:

- TigerGraph Cloud only
- config-driven runtime via `configs/server_config.json`
- Docker Compose for local app services
- no local TigerGraph database container required

## What This Repo Runs

This repo starts these app services locally:

- `graphrag` on port `8000`
- `graphrag-ecc` on port `8001`
- `chat-history` on port `8002`
- `graphrag-ui` on port `3000`
- `nginx` on port `80`

TigerGraph itself is not expected to run locally in this setup. The app connects to a TigerGraph Cloud instance using `configs/server_config.json`.

Important distinction:

- Docker Compose runs the local application services only.
- TigerGraph data storage/query execution runs in TigerGraph Cloud through `db_config.hostname`.
- Hosted LLM/embedding calls run through the providers configured in `llm_config`.
- The default Docker build uses `common/requirements.cloud.txt`, a lighter cloud-runtime dependency set.
- Use `common/requirements.txt` only for the full development/all-provider image.

## Prerequisites

Install these first:

- Git
- Docker Desktop

Recommended:

- VS Code or another IDE

## Clone The Repo

```bash
git clone https://github.com/Vedant988/graphrag.git
cd graphrag
```

If you need a specific branch:

```bash
git checkout main
git pull
```

## Main Runtime File

The most important file is:

```text
configs/server_config.json
```

This repo is intentionally config-driven. Do not depend on `.env` for normal runtime behavior.

## Dependency Profile

The default backend Dockerfiles install:

```text
common/requirements.cloud.txt
```

That file is for the current cloud-only runtime: TigerGraph Cloud plus hosted LLM APIs.

The larger file remains available here:

```text
common/requirements.txt
```

Use the larger file only when you need optional providers or heavier local document-processing features that are not part of the standard friend setup.

To build the full dependency image manually:

```bash
docker compose build --build-arg PYTHON_REQUIREMENTS=common/requirements.txt graphrag graphrag-ecc
docker compose up -d
```

## Fill In `server_config.json`

Open `configs/server_config.json` and replace the placeholder values.

Required TigerGraph Cloud values:

- `db_config.hostname`
- `db_config.username`
- `db_config.password`
- `db_config.apiToken`

Required provider values:

- `llm_config.authentication_configuration.GOOGLE_API_KEY`
- `llm_config.authentication_configuration.GOOGLE_API_KEY_FALLBACK`
- `llm_config.authentication_configuration.GROQ_API_KEY`
- `llm_config.authentication_configuration.HUGGINGFACEHUB_API_TOKEN`

Important:

- keep real secrets out of git
- share secrets privately
- the checked-in file is a template, not a production secret file

## What The Key Sections Mean

`db_config`

Points the app to the TigerGraph Cloud URL and auth.

`graphrag_config`

Internal service wiring like ECC and chat-history.

`llm_config.authentication_configuration`

Shared provider secrets used by the configured LLM services.

`llm_config.completion_service`

Main text generation service.

`llm_config.embedding_service`

Embedding model for retrieval.

`llm_config.multimodal_service`

Model used for image/document multimodal flows.

`llm_config.comparison_service`

Hosted Hugging Face models used by the comparison dashboard for answer evaluation.

## Start From Scratch

Run:

```bash
docker compose up -d --build
```

Then open:

```text
http://localhost
```

Direct service URLs if needed:

- UI: `http://localhost:3000`
- API: `http://localhost:8000`

## Login

Use the TigerGraph credentials that match the values in `configs/server_config.json`:

- `db_config.username`
- `db_config.password`

If login fails, the most common causes are:

- expired `apiToken`
- wrong TigerGraph Cloud hostname
- bad username/password
- provider keys missing from `llm_config.authentication_configuration`

## How This Repo Is Meant To Be Read

If a developer or IDE agent is trying to understand the repo quickly, these are the main files:

- `configs/server_config.json`: runtime configuration and provider setup
- `docker-compose.yml`: local service orchestration
- `common/config.py`: config loading and service resolution
- `graphrag/app/routers/ui.py`: main UI/backend routes including comparison flow
- `graphrag-ui/src/pages/Comparison.tsx`: comparison dashboard frontend
- `common/utils/gemini_fallback.py`: Gemini fallback key collection and token cost helpers

## Rebuild Rules

Use these rules so you do not rebuild more than necessary.

If you change only `configs/server_config.json`, usually recreate backend containers:

```bash
docker compose up -d --force-recreate graphrag graphrag-ecc chat-history
```

If you change backend Python files in `common/`, `graphrag/`, or `ecc/`, rebuild backend services:

```bash
docker compose up -d --build graphrag graphrag-ecc
```

If you change frontend files in `graphrag-ui/`, rebuild UI:

```bash
docker compose up -d --build graphrag-ui
```

If you want the safest full refresh:

```bash
docker compose up -d --build
```

## Useful Checks

See running containers:

```bash
docker compose ps
```

See recent logs:

```bash
docker compose logs --tail=100 graphrag
docker compose logs --tail=100 graphrag-ecc
docker compose logs --tail=100 graphrag-ui
```

See local code changes:

```bash
git status
```

## Common Troubleshooting

### 1. Login Fails

Check:

- `apiToken` is not expired
- `hostname` is the TigerGraph Cloud URL
- ports are `443` for cloud
- username/password match the cloud user

### 2. Comparison Dashboard Runs But Accuracy Is Missing

Check:

- `llm_config.authentication_configuration.HUGGINGFACEHUB_API_TOKEN`
- `llm_config.comparison_service.judge_model`
- `llm_config.comparison_service.similarity_model`

### 3. Gemini Calls Fail

Check:

- `GOOGLE_API_KEY`
- `GOOGLE_API_KEY_FALLBACK`

### 4. UI Looks Old After A Change

Rebuild the UI:

```bash
docker compose up -d --build graphrag-ui
```

### 5. Backend Code Changed But Behavior Did Not

Rebuild backend services:

```bash
docker compose up -d --build graphrag graphrag-ecc
```

## Git Workflow For A Friend

Before starting work:

```bash
git pull
git checkout -b feature/my-change
```

After making changes:

```bash
git status
git add .
git commit -m "Describe the change"
git push -u origin feature/my-change
```

## Notes For IDE Agents

If an IDE agent is helping with this repo, it should assume:

- runtime is config-driven
- TigerGraph runs in the cloud, not in Docker here
- `configs/server_config.json` is the first file to inspect
- secrets must never be committed
- frontend and backend rebuild independently
- comparison dashboard behavior spans both:
  - backend: `graphrag/app/routers/ui.py`
  - frontend: `graphrag-ui/src/pages/Comparison.tsx`

## Safe Sharing Practice

When sharing the repo with another person:

- push code to GitHub
- do not push your real `server_config.json`
- give them either:
  - their own secrets
  - or a private copy of the filled config outside git
