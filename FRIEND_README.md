# GraphRAG Local Setup

This README is for a teammate cloning this repo on a fresh PC.

## 1. Clone The Repo

```bash
git clone https://github.com/Vedant988/graphrag.git
cd graphrag
```

If you need the latest `main` branch:

```bash
git checkout main
git pull
```

## 2. Install Prerequisites

Install these if they are not already available:

- Git
- Docker Desktop

Recommended:

- VS Code or another IDE

## 3. Understand The Current Setup

This repo is currently set up for:

- TigerGraph Cloud only
- config-driven runtime via `configs/server_config.json`
- Docker Compose for local app services
- no local TigerGraph database container

The local Docker services are:

- `graphrag` on port `8000`
- `graphrag-ecc` on port `8001`
- `chat-history` on port `8002`
- `graphrag-ui` on port `3000`
- `nginx` on port `80`

TigerGraph itself is not expected to run locally. The app connects to a TigerGraph Cloud instance using `configs/server_config.json`.

Important distinction:

- Docker Compose runs the local application services only.
- TigerGraph data storage/query execution runs in TigerGraph Cloud through `db_config.hostname`.
- Hosted LLM/embedding calls run through the providers configured in `llm_config`.
- The default Docker build uses `common/requirements.cloud.txt`, a lighter cloud-runtime dependency set.
- Use `common/requirements.txt` only for the full development/all-provider image.

## 4. Fill In `server_config.json`

The most important runtime file is:

```text
configs/server_config.json
```

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
- do not depend on `.env` for normal runtime behavior
- the checked-in config should be treated as a template, not a production secret file

## 4a. Dependency Profile

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

## 5. What The Key Config Sections Mean

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

## 6. Start The App

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

## 7. Login

Use the TigerGraph credentials that match the values in `configs/server_config.json`:

- `db_config.username`
- `db_config.password`

If login fails, the most common causes are:

- expired `apiToken`
- wrong TigerGraph Cloud hostname
- bad username/password
- provider keys missing from `llm_config.authentication_configuration`

## 8. Main Files To Read First

If a developer or IDE agent is trying to understand the repo quickly, these are the main files:

- `configs/server_config.json`: runtime configuration and provider setup
- `docker-compose.yml`: local service orchestration
- `common/config.py`: config loading and service resolution
- `graphrag/app/routers/ui.py`: main UI/backend routes including comparison flow
- `graphrag-ui/src/pages/Comparison.tsx`: comparison dashboard frontend
- `common/utils/gemini_fallback.py`: Gemini fallback key collection and token cost helpers

## 9. Rebuild Rules

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

## 10. Useful Checks

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

## 11. Common Troubleshooting

### Login Fails

Check:

- `apiToken` is not expired
- `hostname` is the TigerGraph Cloud URL
- ports are `443` for cloud
- username/password match the cloud user

### Comparison Dashboard Runs But Accuracy Is Missing

Check:

- `llm_config.authentication_configuration.HUGGINGFACEHUB_API_TOKEN`
- `llm_config.comparison_service.judge_model`
- `llm_config.comparison_service.similarity_model`

### Gemini Calls Fail

Check:

- `GOOGLE_API_KEY`
- `GOOGLE_API_KEY_FALLBACK`

### UI Looks Old After A Change

Rebuild the UI:

```bash
docker compose up -d --build graphrag-ui
```

### Backend Code Changed But Behavior Did Not

Rebuild backend services:

```bash
docker compose up -d --build graphrag graphrag-ecc
```

## 12. Git Workflow For A Friend

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

## 13. Notes For IDE Agents

If an IDE agent is helping with this repo, it should assume:

- runtime is config-driven
- TigerGraph runs in the cloud, not in Docker here
- `configs/server_config.json` is the first file to inspect
- secrets must never be committed
- frontend and backend rebuild independently
- comparison dashboard behavior spans both:
  - backend: `graphrag/app/routers/ui.py`
  - frontend: `graphrag-ui/src/pages/Comparison.tsx`

## 14. Safe Sharing Practice

When sharing the repo with another person:

- push code to GitHub
- do not push your real `server_config.json`
- give them either:
  - their own secrets
  - or a private copy of the filled config outside git
