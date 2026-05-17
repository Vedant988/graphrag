# Render Deployment

This repo is best deployed on Render as Docker services. Keep `configs/server_config.json`
as a safe template and provide real credentials with Render environment variables.

## Service Layout

Create these services in the same Render workspace and region:

| Service | Render type | Dockerfile | Public? |
| --- | --- | --- | --- |
| `graphrag` | Web Service | `graphrag/Dockerfile` | Yes |
| `graphrag-ecc` | Private Service | `ecc/Dockerfile` | No |
| `chat-history` | Private Service | `chat-history/Dockerfile` | No |
| `graphrag-ui` | Web Service | `graphrag-ui/Dockerfile` | Yes |

TigerGraph should stay on TigerGraph Cloud. Do not deploy TigerGraph itself to Render
for the hackathon demo.

## 1. Create Private Services First

Create `graphrag-ecc`:

- Type: Private Service
- Runtime: Docker
- Dockerfile path: `ecc/Dockerfile`
- Port: `8001`
- Environment:
  - `SERVER_CONFIG=/server_config.json`
  - `PRODUCTION=true`
  - `LOGLEVEL=INFO`
  - `INIT_EMBED_STORE=false`
  - TigerGraph and provider variables from your local ignored `.env.render.example`

Create `chat-history`:

- Type: Private Service
- Runtime: Docker
- Root directory: `chat-history`
- Dockerfile path: `Dockerfile`
- Port: `8002`
- Environment:
  - `PORT=8002`
  - `CONFIG_FILES=` can be left empty
  - TigerGraph variables from your local ignored `.env.render.example`

After each private service is created, open its Render **Connect** menu and copy
the internal address. It looks similar to `service-name-xxxx:8001`.

## 2. Create The Backend Web Service

Create `graphrag`:

- Type: Web Service
- Runtime: Docker
- Dockerfile path: `graphrag/Dockerfile`
- Environment:
  - `SERVER_CONFIG=/server_config.json`
  - `PRODUCTION=true`
  - `LOGLEVEL=INFO`
  - `INIT_EMBED_STORE=false`
  - `USE_CYPHER=true`
  - `GRAPHRAG_ECC_URL=http://<graphrag-ecc-internal-address>`
  - `CHAT_HISTORY_API_URL=http://<chat-history-internal-address>`
  - TigerGraph and provider variables from your local ignored `.env.render.example`

When it deploys, test:

```text
https://<graphrag-service>.onrender.com/health
```

## 3. Create The UI Web Service

Create `graphrag-ui`:

- Type: Web Service
- Runtime: Docker
- Root directory: `graphrag-ui`
- Dockerfile path: `Dockerfile`
- Environment:
  - `GRAPHRAG_API_URL=https://<graphrag-service>.onrender.com`

Open the UI service URL. The React app calls `/ui/...`, and the UI Nginx container
proxies those calls to `GRAPHRAG_API_URL`.

## 4. Secrets Checklist

Set these in Render environment variables, not in Git:

- `TIGERGRAPH_HOSTNAME`
- `TIGERGRAPH_USERNAME`
- `TIGERGRAPH_PASSWORD`
- `TIGERGRAPH_API_TOKEN`
- `GOOGLE_API_KEY`
- `GOOGLE_API_KEY_FALLBACK`
- `GOOGLE_API_KEY_FALLBACK_1`
- `GOOGLE_API_KEY_FALLBACK_2`
- `GROQ_API_KEY`
- `HUGGINGFACEHUB_API_TOKEN`

Render can bulk import these from your local ignored `.env.render.example` after
you replace the placeholder values. Do not commit a real `.env` file.

## 5. Hackathon Demo Path

Use the UI URL for the video. Before recording:

1. Open `/health` on the backend service.
2. Open the UI service.
3. Run a benchmark question from the comparison page.
4. Show token count, cost, accuracy score, and latency side by side.
