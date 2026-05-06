import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import requests
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pypdf import PdfReader, PdfWriter


REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = Path(__file__).resolve().parent
DATA_DIR = PILOT_DIR / "data"
OUTPUT_DIR = PILOT_DIR / "output"
QUESTION_FILE = PILOT_DIR / "questions.json"
SOURCE_PDF = REPO_ROOT / "database" / "Mahabharata (Unabridged in English).pdf"
TEN_PAGE_PDF = DATA_DIR / "Mahabharata_first_10_pages.pdf"
TEN_PAGE_TEXT = DATA_DIR / "Mahabharata_first_10_pages.txt"
TEN_PAGE_META = DATA_DIR / "Mahabharata_first_10_pages.meta.json"
EMBEDDING_CACHE = OUTPUT_DIR / "chunk_embeddings_cache.json"
GRAPH_CACHE = OUTPUT_DIR / "graph_extraction_cache.json"
DEBUG_LOG_PATH = OUTPUT_DIR / "graph_debug.log"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_PROACTIVE_TPM_COOLDOWN_TOKENS = 5500
GROQ_PROACTIVE_TPM_COOLDOWN_SECONDS = 60.0
GRAPH_EXTRACTION_CACHE_VERSION = 2
EMBEDDING_CACHE_VERSION = 1


for maybe_proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(maybe_proxy, None)
os.environ["NO_PROXY"] = "*"

sys.path.insert(0, str(REPO_ROOT))

LOGGER = logging.getLogger("mahabharata_10_page_pilot")


GRAPH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "definition": {"type": "string"},
                },
                "required": ["id", "type", "definition"],
                "additionalProperties": False,
            },
        },
        "rels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "type": {"type": "string"},
                    "definition": {"type": "string"},
                },
                "required": ["source", "target", "type", "definition"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["nodes", "rels"],
    "additionalProperties": False,
}


@dataclass
class PilotConfig:
    groq_model: str
    gemini_embedding_model: str
    max_pages: int
    chunk_size: int
    chunk_overlap: int
    top_k: int
    question_id: str | None
    graph_only: bool
    all_questions: bool


class GeminiEmbedder:
    def __init__(self, model_name: str, api_key: str, dimensions: int = 1536):
        self.model_name = model_name if model_name.startswith("models/") else f"models/{model_name}"
        self.dimensions = dimensions
        os.environ["GOOGLE_API_KEY"] = api_key
        self.client = GoogleGenerativeAIEmbeddings(model=self.model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed_documents(texts, output_dimensionality=self.dimensions)

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed_query(text, output_dimensionality=self.dimensions)


def parse_args() -> PilotConfig:
    parser = argparse.ArgumentParser(description="Run a 10-page Mahabharata pilot for LLM, RAG, and GraphRAG-style flows.")
    parser.add_argument("--groq-model", default="openai/gpt-oss-120b")
    parser.add_argument("--gemini-embedding-model", default="models/gemini-embedding-001")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--chunk-size", type=int, default=6000)
    parser.add_argument("--chunk-overlap", type=int, default=400)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--question-id", default=None)
    parser.add_argument("--graph-only", action="store_true")
    parser.add_argument("--all-questions", action="store_true")
    args = parser.parse_args()
    return PilotConfig(
        groq_model=args.groq_model,
        gemini_embedding_model=args.gemini_embedding_model,
        max_pages=args.max_pages,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        top_k=args.top_k,
        question_id=args.question_id,
        graph_only=args.graph_only,
        all_questions=args.all_questions,
    )


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.handlers.clear()
    handler = logging.FileHandler(DEBUG_LOG_PATH, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    LOGGER.propagate = False
    LOGGER.info("Logging initialized")


def load_env() -> tuple[str, str]:
    load_dotenv(REPO_ROOT / ".env")
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not groq_api_key:
        raise RuntimeError("GROQ_API_KEY not found in repo root .env")
    if not google_api_key:
        raise RuntimeError("GOOGLE_API_KEY not found in repo root .env")
    return groq_api_key, google_api_key


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_print(text: str = "") -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.buffer.write((text + "\n").encode(encoding, errors="replace"))
    sys.stdout.flush()


ASCII_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\u2026": "...",
    "\u00a0": " ",
    "\u202f": " ",
    "\u3010": "[",
    "\u3011": "]",
}

NODE_TYPE_PRIORITY = {
    "narrator": 6,
    "sage": 5,
    "deity": 5,
    "king": 4,
    "person": 4,
    "place": 4,
    "work": 4,
    "parva": 4,
    "group": 3,
    "concept": 2,
    "entity": 1,
}

HONORIFIC_PREFIXES = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "miss",
    "sir",
    "babu",
    "professor",
    "pundit",
    "raja",
    "king",
}


def sanitize_model_text(text: str) -> str:
    for source, target in ASCII_REPLACEMENTS.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n", "\n", text)
    return text.strip()


def prepare_sample_assets(max_pages: int) -> dict[str, Any]:
    source_stat = SOURCE_PDF.stat()
    if TEN_PAGE_META.exists() and TEN_PAGE_PDF.exists() and TEN_PAGE_TEXT.exists():
        try:
            cached = json.loads(TEN_PAGE_META.read_text(encoding="utf-8"))
            if (
                cached.get("source_pdf") == str(SOURCE_PDF)
                and cached.get("pages") == max_pages
                and cached.get("source_size") == source_stat.st_size
                and cached.get("source_mtime_ns") == source_stat.st_mtime_ns
            ):
                LOGGER.info("Sample asset cache hit for %s pages", max_pages)
                return cached
        except (json.JSONDecodeError, OSError, ValueError):
            LOGGER.exception("Failed to read sample metadata cache")

    reader = PdfReader(str(SOURCE_PDF))
    writer = PdfWriter()
    texts: list[str] = []

    for page in reader.pages[:max_pages]:
        writer.add_page(page)
        texts.append(page.extract_text() or "")

    joined = "\n".join(texts)
    with TEN_PAGE_PDF.open("wb") as handle:
        writer.write(handle)
    TEN_PAGE_TEXT.write_text(joined, encoding="utf-8")

    metadata = {
        "source_pdf": str(SOURCE_PDF),
        "sample_pdf": str(TEN_PAGE_PDF),
        "sample_text": str(TEN_PAGE_TEXT),
        "pages": max_pages,
        "chars": len(joined),
        "words": len(joined.split()),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "sample_text_sha256": sha256_text(joined),
    }
    TEN_PAGE_META.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    LOGGER.info("Prepared sample assets for %s pages chars=%s words=%s", max_pages, metadata["chars"], metadata["words"])
    return metadata


def load_questions() -> list[dict[str, str]]:
    return json.loads(QUESTION_FILE.read_text(encoding="utf-8"))


def select_question(questions: list[dict[str, str]], question_id: str | None) -> dict[str, str]:
    if question_id is None:
        return questions[0]
    for question in questions:
        if question["id"] == question_id:
            return question
    raise ValueError(f"Question id '{question_id}' not found in {QUESTION_FILE}")


def select_questions(questions: list[dict[str, str]], question_id: str | None, all_questions: bool) -> list[dict[str, str]]:
    if all_questions:
        return questions
    return [select_question(questions, question_id)]


def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        LOGGER.debug("Cache/file missing: %s", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        LOGGER.debug("Loaded JSON file: %s", path)
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        LOGGER.exception("Failed to load JSON file: %s", path)
        return None


def embedding_cache_key(sample_text: str, config: PilotConfig, dimensions: int) -> dict[str, Any]:
    return {
        "version": EMBEDDING_CACHE_VERSION,
        "sample_text_sha256": sha256_text(sample_text),
        "chunk_size": config.chunk_size,
        "chunk_overlap": config.chunk_overlap,
        "gemini_embedding_model": config.gemini_embedding_model,
        "dimensions": dimensions,
    }


def graph_cache_key(sample_text: str, config: PilotConfig) -> dict[str, Any]:
    return {
        "version": GRAPH_EXTRACTION_CACHE_VERSION,
        "sample_text_sha256": sha256_text(sample_text),
        "chunk_size": config.chunk_size,
        "chunk_overlap": config.chunk_overlap,
        "groq_model": config.groq_model,
    }


class GroqClient:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.session = requests.Session()
        self.calls: list[dict[str, Any]] = []
        self.proactive_tpm_cooldown_tokens = GROQ_PROACTIVE_TPM_COOLDOWN_TOKENS
        self.proactive_tpm_cooldown_seconds = GROQ_PROACTIVE_TPM_COOLDOWN_SECONDS
        self.last_seen_remaining_tokens: int | None = None
        self.last_seen_reset_tokens_seconds: float | None = None
        self.last_seen_tokens_timestamp: float | None = None
        self.preflight_tpm_safety_margin = 500

    @staticmethod
    def _parse_reset_duration(value: str | None) -> float:
        if not value:
            return 0.0
        value = value.strip().lower()
        if value.endswith("ms"):
            return float(value[:-2]) / 1000.0
        total = 0.0
        if "m" in value:
            mins, rest = value.split("m", 1)
            total += float(mins) * 60
            value = rest
        if value.endswith("s"):
            total += float(value[:-1])
        return total

    def _estimate_request_tokens(self, messages: list[dict[str, str]], max_completion_tokens: int) -> int:
        prompt_chars = sum(len(message.get("content", "")) for message in messages)
        estimated_prompt_tokens = max(1, int(prompt_chars / 3.2))
        return estimated_prompt_tokens + max_completion_tokens

    def _update_last_seen_token_budget(self, headers: dict[str, str]) -> None:
        remaining_tokens_header = headers.get("x-ratelimit-remaining-tokens")
        reset_tokens_header = headers.get("x-ratelimit-reset-tokens")
        if remaining_tokens_header is not None:
            try:
                self.last_seen_remaining_tokens = int(remaining_tokens_header)
            except ValueError:
                self.last_seen_remaining_tokens = None
        if reset_tokens_header is not None:
            self.last_seen_reset_tokens_seconds = self._parse_reset_duration(reset_tokens_header)
        self.last_seen_tokens_timestamp = time.time()

    def _maybe_wait_for_tpm_budget(self, messages: list[dict[str, str]], max_completion_tokens: int) -> float:
        if self.last_seen_remaining_tokens is None:
            return 0.0
        estimated_needed = self._estimate_request_tokens(messages, max_completion_tokens) + self.preflight_tpm_safety_margin
        if self.last_seen_remaining_tokens >= estimated_needed:
            return 0.0

        wait_seconds = self.last_seen_reset_tokens_seconds or self.proactive_tpm_cooldown_seconds
        if wait_seconds <= 0:
            wait_seconds = self.proactive_tpm_cooldown_seconds
        time.sleep(wait_seconds + 0.25)
        self.last_seen_remaining_tokens = None
        self.last_seen_reset_tokens_seconds = None
        self.last_seen_tokens_timestamp = None
        return wait_seconds + 0.25

    def chat(
        self,
        messages: list[dict[str, str]],
        max_completion_tokens: int = 600,
        temperature: float = 0.0,
        max_retries: int = 3,
        response_format: dict[str, Any] | None = None,
        include_reasoning: bool | None = None,
        reasoning_effort: str | None = None,
        allow_schema_failure: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if include_reasoning is not None:
            payload["include_reasoning"] = include_reasoning
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort

        preflight_wait = self._maybe_wait_for_tpm_budget(messages, max_completion_tokens)
        for attempt in range(max_retries + 1):
            response = self.session.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            body = response.json()
            headers = {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower().startswith("x-ratelimit-") or key.lower() == "retry-after"
            }
            record = {
                "model": self.model,
                "status_code": response.status_code,
                "usage": body.get("usage"),
                "headers": headers,
            }
            if preflight_wait > 0 and attempt == 0:
                record["preflight_wait_seconds"] = preflight_wait
            self.calls.append(record)
            self._update_last_seen_token_budget(headers)

            if response.status_code < 400:
                usage = body.get("usage") or {}
                remaining_tokens = int(headers.get("x-ratelimit-remaining-tokens", "0") or "0")
                total_tokens = int(usage.get("total_tokens", "0") or "0")
                proactive_cooldown = 0.0
                if total_tokens >= self.proactive_tpm_cooldown_tokens:
                    proactive_cooldown = max(
                        proactive_cooldown,
                        self.proactive_tpm_cooldown_seconds,
                    )
                if remaining_tokens and remaining_tokens < 1200:
                    proactive_cooldown = max(
                        proactive_cooldown,
                        self._parse_reset_duration(headers.get("x-ratelimit-reset-tokens")) + 0.25,
                    )
                if proactive_cooldown > 0:
                    record["cooldown_applied_seconds"] = proactive_cooldown
                    record["cooldown_reason"] = (
                        f"total_tokens={total_tokens} remaining_tpm={remaining_tokens}"
                    )
                    time.sleep(proactive_cooldown)
                return body

            error = body.get("error", {})
            if response.status_code == 429 and attempt < max_retries:
                retry_after = headers.get("retry-after")
                reset_tokens = headers.get("x-ratelimit-reset-tokens")
                sleep_seconds = max(
                    self._parse_reset_duration(retry_after),
                    self._parse_reset_duration(reset_tokens),
                    1.0,
                )
                time.sleep(sleep_seconds + 0.25)
                continue

            if allow_schema_failure and response.status_code == 400:
                failed_generation = error.get("failed_generation")
                if failed_generation:
                    return {
                        "choices": [{"message": {"content": failed_generation}}],
                        "usage": body.get("usage"),
                        "error": error,
                    }

            raise RuntimeError(f"Groq call failed: {response.status_code} {body}")

        raise RuntimeError("Groq call failed after retries")


def groq_text_answer(client: GroqClient, system_prompt: str, user_prompt: str, max_completion_tokens: int = 500) -> dict[str, Any]:
    body = client.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
    )
    choice = sanitize_model_text(body["choices"][0]["message"]["content"])
    return {"text": choice, "usage": body.get("usage")}


def clip_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[Truncated for quota-safe testing.]"


def join_blocks(blocks: list[str], max_chars: int) -> str:
    parts: list[str] = []
    used = 0
    for block in blocks:
        separator = "\n\n" if parts else ""
        remaining = max_chars - used - len(separator)
        if remaining <= 0:
            break
        snippet = block[:remaining]
        parts.append(separator + snippet if separator else snippet)
        used += len(separator) + len(snippet)
    return "".join(parts)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be zero or positive")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    step = chunk_size - chunk_overlap
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += step
    return [
        {"chunk_id": f"chunk_{idx:03d}", "text": chunk}
        for idx, chunk in enumerate(chunks)
    ]


def load_or_embed_chunks(embedder: GeminiEmbedder, chunks: list[dict[str, Any]], sample_text: str, config: PilotConfig) -> tuple[list[dict[str, Any]], bool]:
    cache_key = embedding_cache_key(sample_text, config, embedder.dimensions)
    cached = load_json_file(EMBEDDING_CACHE)
    if cached and cached.get("cache_key") == cache_key:
        cached_chunks = cached.get("chunks", [])
        if len(cached_chunks) == len(chunks) and all(
            cached_chunk.get("chunk_id") == chunk["chunk_id"] and cached_chunk.get("text") == chunk["text"]
            for cached_chunk, chunk in zip(cached_chunks, chunks)
        ):
            restored = []
            for cached_chunk in cached_chunks:
                restored.append(
                    {
                        "chunk_id": cached_chunk["chunk_id"],
                        "text": cached_chunk["text"],
                        "embedding": cached_chunk["embedding"],
                    }
                )
            LOGGER.info("Embedding cache hit chunks=%s", len(restored))
            return restored, True

    LOGGER.info("Embedding cache miss chunks=%s", len(chunks))
    chunk_vectors = embedder.embed_documents([chunk["text"] for chunk in chunks])
    enriched_chunks = []
    for chunk, vector in zip(chunks, chunk_vectors):
        enriched_chunks.append({**chunk, "embedding": vector})

    EMBEDDING_CACHE.write_text(
        json.dumps(
            {
                "cache_key": cache_key,
                "chunks": enriched_chunks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    LOGGER.info("Embedding cache written: %s", EMBEDDING_CACHE)
    return enriched_chunks, False


def rank_chunks(chunks: list[dict[str, Any]], question_vector: list[float], top_k: int) -> list[dict[str, Any]]:
    q = np.array(question_vector, dtype=float)
    ranked = []
    for chunk in chunks:
        score = cosine_similarity(np.array(chunk["embedding"], dtype=float), q)
        ranked.append({**chunk, "score": score})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def parse_json_output(content: str) -> dict[str, Any]:
    try:
        return json.loads(content.strip("content="))
    except (json.JSONDecodeError, ValueError):
        pass

    if "```json" in content:
        try:
            return json.loads(content.split("```")[1].strip("```").strip("json").strip())
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = content[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            repaired = repair_json_like_output(candidate)
            return json.loads(repaired)

    raise ValueError(f"Could not parse extractor JSON: {content[:200]}")


def repair_json_like_output(content: str) -> str:
    repaired = content.strip()
    repaired = repaired.replace("```json", "").replace("```", "").strip()
    for _ in range(4):
        updated = re.sub(r'\{\s*"":\s*(\{[^{}]*\})\s*\}', r"\1", repaired)
        if updated == repaired:
            break
        repaired = updated
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    return repaired


def normalize_entity_id(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = value.strip(".,;:!?()[]{}\"'")
    return value


def normalize_node_type(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9 ]+", " ", value).strip().lower()
    return value or "entity"


def normalize_relation_type(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9 ]+", " ", value).strip().upper()
    value = re.sub(r"\s+", "_", value)
    return value or "RELATED_TO"


def alias_lookup_key(value: str) -> str:
    value = sanitize_model_text(value)
    value = value.replace("_", " ").replace("-", " ")
    value = re.sub(r"[^a-zA-Z0-9 ]+", " ", value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    parts = value.split()
    while parts and parts[0] in HONORIFIC_PREFIXES:
        parts = parts[1:]
    return " ".join(parts)


def choose_better_type(current_type: str, candidate_type: str) -> str:
    current_rank = NODE_TYPE_PRIORITY.get(current_type, 0)
    candidate_rank = NODE_TYPE_PRIORITY.get(candidate_type, 0)
    if candidate_rank > current_rank:
        return candidate_type
    return current_type


def choose_better_definition(current_definition: str, candidate_definition: str) -> str:
    current_definition = current_definition.strip()
    candidate_definition = candidate_definition.strip()
    if not current_definition:
        return candidate_definition
    if not candidate_definition:
        return current_definition
    if len(candidate_definition) > len(current_definition):
        return candidate_definition
    return current_definition


def canonicalize_entity_id(node_id: str, node_type: str, definition: str) -> str:
    key = alias_lookup_key(node_id)
    definition_key = alias_lookup_key(definition)

    if node_type in {"person", "sage", "narrator"}:
        if key in {"vyasa", "dwaipayana", "krishna dwaipayana", "krishna dwaipayana vyasa"}:
            return "Vyasa"
        if "krishna dwaipayana" in key or " krishna dwaipayana " in f" {key} ":
            return "Vyasa"
        if key in {"sauti", "ugrasrava", "ugrasrava sauti", "lomaharshana s son ugrasrava"}:
            return "Sauti"
        if "son of lomaharshana" in definition_key and key in {"sauti", "ugrasrava"}:
            return "Sauti"
        if key in {"vaisampayana", "vaisampayana rishi"}:
            return "Vaisampayana"

    if node_type in {"work", "concept", "parva"}:
        if key in {"bharata", "mahabharata", "great bharata"}:
            return "Mahabharata"

    if node_type == "deity":
        if key in {"ganesa", "ganesha"}:
            return "Ganesa"

    if key == "naimisha":
        return "Naimisha"
    if key == "janamejaya":
        return "Janamejaya"
    if key == "dhritarashtra":
        return "Dhritarashtra"

    return node_id


def canonicalize_chunk_graph(chunk_graph: dict[str, Any]) -> dict[str, Any]:
    canonical_nodes: dict[str, dict[str, Any]] = {}
    node_alias_map: dict[str, str] = {}
    node_merges: list[dict[str, str]] = []
    dropped_relationships: list[dict[str, str]] = []
    dropped_nodes: list[str] = []

    for node in chunk_graph["nodes"]:
        canonical_id = canonicalize_entity_id(node["id"], node["type"], node["definition"])
        node_alias_map[node["id"]] = canonical_id
        if canonical_id != node["id"]:
            node_merges.append({"from": node["id"], "to": canonical_id})
        if canonical_id not in canonical_nodes:
            canonical_nodes[canonical_id] = {
                "id": canonical_id,
                "type": node["type"],
                "definition": node["definition"],
            }
            continue
        canonical_nodes[canonical_id]["type"] = choose_better_type(
            canonical_nodes[canonical_id]["type"],
            node["type"],
        )
        canonical_nodes[canonical_id]["definition"] = choose_better_definition(
            canonical_nodes[canonical_id]["definition"],
            node["definition"],
        )

    canonical_rels: list[dict[str, Any]] = []
    seen_rels: set[tuple[str, str, str]] = set()
    for rel in chunk_graph["rels"]:
        source = node_alias_map.get(rel["source"], rel["source"])
        target = node_alias_map.get(rel["target"], rel["target"])
        if source == target:
            dropped_relationships.append({"reason": "self_loop_after_canonicalization", "source": source, "target": target, "type": rel["type"]})
            continue
        if source not in canonical_nodes or target not in canonical_nodes:
            dropped_relationships.append({"reason": "missing_endpoint_after_canonicalization", "source": source, "target": target, "type": rel["type"]})
            continue
        rel_key = (source, target, rel["type"])
        if rel_key in seen_rels:
            dropped_relationships.append({"reason": "duplicate_relationship", "source": source, "target": target, "type": rel["type"]})
            continue
        seen_rels.add(rel_key)
        canonical_rels.append(
            {
                "source": source,
                "target": target,
                "type": rel["type"],
                "definition": rel["definition"],
            }
        )

    if canonical_rels:
        participating = {rel["source"] for rel in canonical_rels} | {rel["target"] for rel in canonical_rels}
        essential_isolates = {"Mahabharata", "Vyasa", "Sauti", "Ganesa"}
        filtered_nodes = [
            node
            for canonical_id, node in canonical_nodes.items()
            if canonical_id in participating or canonical_id in essential_isolates
        ]
        dropped_nodes = [
            canonical_id
            for canonical_id in canonical_nodes
            if canonical_id not in {node["id"] for node in filtered_nodes}
        ]
    else:
        filtered_nodes = list(canonical_nodes.values())

    filtered_node_ids = {node["id"] for node in filtered_nodes}
    filtered_rels = [
        rel for rel in canonical_rels
        if rel["source"] in filtered_node_ids and rel["target"] in filtered_node_ids
    ]

    diagnostics = {
        "raw_node_count": len(chunk_graph["nodes"]),
        "raw_rel_count": len(chunk_graph["rels"]),
        "canonical_node_count_before_filter": len(canonical_nodes),
        "canonical_rel_count_before_filter": len(canonical_rels),
        "final_node_count": len(filtered_nodes),
        "final_rel_count": len(filtered_rels),
        "node_merges": node_merges,
        "dropped_relationships": dropped_relationships,
        "dropped_nodes": dropped_nodes,
        "node_alias_map": node_alias_map,
    }
    LOGGER.debug(
        "Chunk %s canonicalization raw_nodes=%s raw_rels=%s final_nodes=%s final_rels=%s merges=%s dropped_rels=%s",
        chunk_graph.get("chunk_id"),
        diagnostics["raw_node_count"],
        diagnostics["raw_rel_count"],
        diagnostics["final_node_count"],
        diagnostics["final_rel_count"],
        len(node_merges),
        len(dropped_relationships),
    )

    return {
        **chunk_graph,
        "nodes": filtered_nodes,
        "rels": filtered_rels,
        "diagnostics": diagnostics,
    }


def _normalized_graph_from_raw(raw: dict[str, Any], usage: dict[str, Any] | None, raw_text: str) -> dict[str, Any]:
    nodes = []
    seen_nodes: set[str] = set()
    for node in raw.get("nodes", []):
        node_id = normalize_entity_id(sanitize_model_text(str(node.get("id", ""))))
        if not node_id or node_id.lower() in {"none", "null", "unknown"}:
            continue
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "type": normalize_node_type(sanitize_model_text(str(node.get("type", "entity")))),
                "definition": sanitize_model_text(str(node.get("definition", ""))),
            }
        )

    rels = []
    valid_node_ids = {node["id"] for node in nodes}
    seen_rels: set[tuple[str, str, str]] = set()
    for rel in raw.get("rels", []):
        src_id = normalize_entity_id(sanitize_model_text(str(rel.get("source", ""))))
        tgt_id = normalize_entity_id(sanitize_model_text(str(rel.get("target", ""))))
        rel_type = normalize_relation_type(sanitize_model_text(str(rel.get("type", ""))))
        if not src_id or not tgt_id or src_id == tgt_id:
            continue
        if src_id not in valid_node_ids or tgt_id not in valid_node_ids:
            continue
        rel_key = (src_id, tgt_id, rel_type)
        if rel_key in seen_rels:
            continue
        seen_rels.add(rel_key)
        rels.append(
            {
                "source": str(src_id),
                "target": str(tgt_id),
                "type": rel_type,
                "definition": sanitize_model_text(str(rel.get("definition", ""))),
            }
        )

    return {"nodes": nodes, "rels": rels, "usage": usage, "raw_text": sanitize_model_text(raw_text)}


def extract_chunk_graph(client: GroqClient, chunk_text_value: str) -> dict[str, Any]:
    instructions = (
        "Extract a small knowledge graph from the passage.\n"
        "Return JSON only.\n"
        "Rules:\n"
        "- Include only entities explicitly grounded in the passage.\n"
        "- Prefer named entities and key concepts central to the passage.\n"
        "- Use short, human-readable entity ids exactly as named in the text when possible.\n"
        "- Resolve aliases to a single canonical id inside the same passage. Examples: Krishna-Dwaipayana Vyasa, Dwaipayana, and Vyasa should all use Vyasa. Ugrasrava and Sauti should use Sauti. Bharata and Mahabharata should use Mahabharata when referring to the epic.\n"
        "- Use simple node types like person, place, work, event, group, concept, deity, sage, king, narrator.\n"
        "- Relationships must connect existing node ids.\n"
        "- Relationship types should be short labels such as NARRATES, COMPOSED, ATTENDS, SON_OF, TAKES_PLACE_IN.\n"
        "- Prefer entities that participate in relationships. Avoid creating many isolated duplicate nodes.\n"
        "- If the passage contains no relationship, still return useful nodes and an empty rels list.\n"
        "- Keep the graph concise: at most 14 nodes and 18 relationships.\n\n"
        f"Passage:\n{chunk_text_value}"
    )
    attempts = [
        {
            "name": "json_schema_strict",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "knowledge_graph_extraction",
                    "strict": True,
                    "schema": GRAPH_RESPONSE_SCHEMA,
                },
            },
            "allow_schema_failure": True,
        },
        {
            "name": "json_schema_best_effort",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "knowledge_graph_extraction",
                    "strict": False,
                    "schema": GRAPH_RESPONSE_SCHEMA,
                },
            },
            "allow_schema_failure": True,
        },
        {
            "name": "json_object",
            "response_format": {"type": "json_object"},
            "allow_schema_failure": False,
        },
        {
            "name": "plain_text_json",
            "response_format": None,
            "allow_schema_failure": False,
        },
    ]

    last_usage: dict[str, Any] | None = None
    last_raw_text = ""
    for attempt in attempts:
        LOGGER.debug("Extraction attempt=%s text_chars=%s", attempt["name"], len(chunk_text_value))
        try:
            body = client.chat(
                messages=[{"role": "user", "content": instructions}],
                max_completion_tokens=700,
                response_format=attempt["response_format"],
                include_reasoning=False,
                reasoning_effort="low",
                allow_schema_failure=attempt["allow_schema_failure"],
            )
        except RuntimeError as exc:
            last_raw_text = str(exc)
            LOGGER.warning("Extraction attempt failed attempt=%s error=%s", attempt["name"], exc)
            continue

        content = body["choices"][0]["message"]["content"]
        last_usage = body.get("usage")
        last_raw_text = content
        try:
            raw = parse_json_output(content)
        except Exception:
            LOGGER.exception("JSON parse failed for extraction attempt=%s content_preview=%s", attempt["name"], content[:300])
            continue

        raw_nodes = len(raw.get("nodes", [])) if isinstance(raw, dict) else 0
        raw_rels = len(raw.get("rels", [])) if isinstance(raw, dict) and isinstance(raw.get("rels", []), list) else 0
        LOGGER.debug("Extraction parsed attempt=%s raw_nodes=%s raw_rels=%s", attempt["name"], raw_nodes, raw_rels)
        graph = _normalized_graph_from_raw(raw, last_usage, content)
        if graph["nodes"] or graph["rels"]:
            graph["mode"] = attempt["name"]
            graph["raw_counts"] = {"nodes": raw_nodes, "rels": raw_rels}
            if raw_nodes > 1 and raw_rels == 0:
                LOGGER.warning("Node-only extraction accepted attempt=%s nodes=%s rels=%s", attempt["name"], raw_nodes, raw_rels)
            return graph

    LOGGER.error("All extraction attempts failed content_preview=%s", sanitize_model_text(last_raw_text)[:300])
    return {"nodes": [], "rels": [], "usage": last_usage, "raw_text": sanitize_model_text(last_raw_text), "mode": "failed", "raw_counts": {"nodes": 0, "rels": 0}}


def load_or_extract_chunk_graphs(client: GroqClient, chunks: list[dict[str, Any]], sample_text: str, config: PilotConfig) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    cache_key = graph_cache_key(sample_text, config)
    cached = load_json_file(GRAPH_CACHE)
    if cached and cached.get("cache_key") == cache_key:
        cached_chunk_graphs = cached.get("chunk_graphs", [])
        if len(cached_chunk_graphs) == len(chunks) and all(
            cached_chunk.get("chunk_id") == chunk["chunk_id"] and cached_chunk.get("text") == chunk["text"]
            for cached_chunk, chunk in zip(cached_chunk_graphs, chunks)
        ):
            cached_summary = cached.get("extraction_summary", {})
            LOGGER.info("Graph extraction cache hit chunks=%s", len(cached_chunk_graphs))
            return cached_chunk_graphs, cached_summary, True

    LOGGER.info("Graph extraction cache miss chunks=%s", len(chunks))
    chunk_graphs: list[dict[str, Any]] = []
    extraction_usage: list[dict[str, Any]] = []
    for chunk in chunks:
        extracted = extract_chunk_graph(
            client=client,
            chunk_text_value=clip_text(chunk["text"], 4200),
        )
        chunk_graph = canonicalize_chunk_graph({
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "nodes": extracted["nodes"],
            "rels": extracted["rels"],
            "raw_text": extracted["raw_text"],
            "mode": extracted.get("mode", "unknown"),
            "raw_counts": extracted.get("raw_counts", {"nodes": 0, "rels": 0}),
        })
        extraction_usage.append(
            {
                "chunk_id": chunk["chunk_id"],
                "usage": extracted["usage"],
                "node_count": len(chunk_graph["nodes"]),
                "relationship_count": len(chunk_graph["rels"]),
                "mode": extracted.get("mode", "unknown"),
                "raw_node_count": extracted.get("raw_counts", {}).get("nodes", 0),
                "raw_relationship_count": extracted.get("raw_counts", {}).get("rels", 0),
                "diagnostics": chunk_graph.get("diagnostics", {}),
            }
        )
        LOGGER.info(
            "Chunk extraction result chunk=%s mode=%s raw_nodes=%s raw_rels=%s final_nodes=%s final_rels=%s",
            chunk["chunk_id"],
            extracted.get("mode", "unknown"),
            extracted.get("raw_counts", {}).get("nodes", 0),
            extracted.get("raw_counts", {}).get("rels", 0),
            len(chunk_graph["nodes"]),
            len(chunk_graph["rels"]),
        )
        chunk_graphs.append(chunk_graph)

    extraction_summary = {
        "chunk_extraction_calls": len(chunk_graphs),
        "total_extracted_nodes": sum(len(chunk["nodes"]) for chunk in chunk_graphs),
        "total_extracted_relationships": sum(len(chunk["rels"]) for chunk in chunk_graphs),
        "per_chunk_usage": extraction_usage,
    }
    GRAPH_CACHE.write_text(
        json.dumps(
            {
                "cache_key": cache_key,
                "chunk_graphs": chunk_graphs,
                "extraction_summary": extraction_summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    LOGGER.info(
        "Graph extraction cache written chunks=%s total_nodes=%s total_rels=%s path=%s",
        len(chunk_graphs),
        extraction_summary["total_extracted_nodes"],
        extraction_summary["total_extracted_relationships"],
        GRAPH_CACHE,
    )
    return chunk_graphs, extraction_summary, False


def build_graph(chunk_graphs: list[dict[str, Any]]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    edge_insertions = 0
    for chunk in chunk_graphs:
        chunk_id = chunk["chunk_id"]
        for node in chunk["nodes"]:
            if not graph.has_node(node["id"]):
                graph.add_node(
                    node["id"],
                    type=node["type"],
                    definition=node["definition"],
                    chunk_ids=set(),
                )
            else:
                graph.nodes[node["id"]]["type"] = choose_better_type(
                    graph.nodes[node["id"]]["type"],
                    node["type"],
                )
                graph.nodes[node["id"]]["definition"] = choose_better_definition(
                    graph.nodes[node["id"]]["definition"],
                    node["definition"],
                )
            graph.nodes[node["id"]]["chunk_ids"].add(chunk_id)
        for rel in chunk["rels"]:
            graph.add_edge(
                rel["source"],
                rel["target"],
                key=f"{chunk_id}:{rel['type']}:{rel['source']}:{rel['target']}",
                type=rel["type"],
                definition=rel["definition"],
                chunk_id=chunk_id,
            )
            edge_insertions += 1
        LOGGER.debug(
            "Build graph chunk=%s nodes=%s rels=%s cumulative_graph_nodes=%s cumulative_graph_edges=%s",
            chunk_id,
            len(chunk["nodes"]),
            len(chunk["rels"]),
            graph.number_of_nodes(),
            graph.number_of_edges(),
        )
    LOGGER.info(
        "Graph build complete graph_nodes=%s graph_edges=%s inserted_edges=%s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        edge_insertions,
    )
    return graph


def graph_context(graph: nx.MultiDiGraph, chunk_graphs: list[dict[str, Any]], top_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunk_graphs}
    seed_chunk_ids = [chunk["chunk_id"] for chunk in top_chunks]
    seed_entities: set[str] = set()
    for chunk_id in seed_chunk_ids:
        for node in chunk_by_id[chunk_id]["nodes"]:
            seed_entities.add(node["id"])

    expanded_entities: set[str] = set(seed_entities)
    for entity_id in list(seed_entities):
        if graph.has_node(entity_id):
            expanded_entities.update(graph.predecessors(entity_id))
            expanded_entities.update(graph.successors(entity_id))

    related_relationships: list[dict[str, Any]] = []
    related_chunk_ids: set[str] = set(seed_chunk_ids)
    for source, target, attrs in graph.edges(data=True):
        if source in expanded_entities or target in expanded_entities:
            related_relationships.append(
                {
                    "source": source,
                    "target": target,
                    "type": attrs["type"],
                    "definition": attrs["definition"],
                    "chunk_id": attrs["chunk_id"],
                }
            )
            related_chunk_ids.add(attrs["chunk_id"])

    related_entities = []
    for entity_id in sorted(expanded_entities):
        if graph.has_node(entity_id):
            attrs = graph.nodes[entity_id]
            related_entities.append(
                {
                    "id": entity_id,
                    "type": attrs["type"],
                    "definition": attrs["definition"],
                    "chunk_ids": sorted(attrs["chunk_ids"]),
                }
            )

    related_chunks = [chunk_by_id[chunk_id] for chunk_id in sorted(related_chunk_ids)]
    return {
        "seed_chunk_ids": seed_chunk_ids,
        "related_entities": related_entities,
        "related_relationships": related_relationships,
        "related_chunks": related_chunks,
    }


def compact_chunk_view(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk["chunk_id"],
            "score": round(chunk.get("score", 0.0), 6),
            "text_preview": chunk["text"][:350],
        }
        for chunk in chunks
    ]


def main() -> None:
    ensure_dirs()
    setup_logging()
    config = parse_args()
    LOGGER.info(
        "Pilot start model=%s embedding_model=%s max_pages=%s chunk_size=%s chunk_overlap=%s top_k=%s graph_only=%s all_questions=%s question_id=%s",
        config.groq_model,
        config.gemini_embedding_model,
        config.max_pages,
        config.chunk_size,
        config.chunk_overlap,
        config.top_k,
        config.graph_only,
        config.all_questions,
        config.question_id,
    )
    groq_api_key, google_api_key = load_env()
    metadata = prepare_sample_assets(config.max_pages)
    questions = load_questions()
    questions_to_run = select_questions(questions, config.question_id, config.all_questions)
    sample_text = TEN_PAGE_TEXT.read_text(encoding="utf-8")

    print(f"Prepared {metadata['pages']} pages with {metadata['chars']} chars and {metadata['words']} words.")

    embedder = GeminiEmbedder(
        model_name=config.gemini_embedding_model,
        api_key=google_api_key,
        dimensions=1536,
    )
    groq_client = GroqClient(groq_api_key, config.groq_model)

    chunks = chunk_text(sample_text, config.chunk_size, config.chunk_overlap)
    chunks, embedding_cache_hit = load_or_embed_chunks(embedder, chunks, sample_text, config)

    print(f"Generated {len(chunks)} chunks.")
    print(f"Chunk embedding cache: {'hit' if embedding_cache_hit else 'miss'}")
    print(f"Questions to run: {[question['id'] for question in questions_to_run]}")

    llm_answer: dict[str, Any] | None = None
    rag_answer: dict[str, Any] | None = None
    selected_question = questions_to_run[0]
    selected_top_chunks: list[dict[str, Any]] = []
    if not config.graph_only:
        selected_question_vector = embedder.embed_query(selected_question["question"])
        selected_top_chunks = rank_chunks(chunks, selected_question_vector, config.top_k)
        print(f"Question: {selected_question['question']}")
        print(f"Top {config.top_k} chunk ids: {[chunk['chunk_id'] for chunk in selected_top_chunks]}")

        llm_source_text = clip_text(sample_text, 22000)
        llm_answer = groq_text_answer(
            groq_client,
            system_prompt="Answer the question using only the provided source text. If the answer is not grounded in the text, say that clearly. Use plain ASCII only. Output only characters in the ASCII range 32-126 plus newline. Do not introduce diacritics, typographic quotes, Unicode dashes, special spaces, or transliterated spellings not present in the source text. Prefer simple spellings like Vyasa, Ganesa, Naimisha, and Mahabharata.",
            user_prompt=f"Question: {selected_question['question']}\n\nSource text:\n{llm_source_text}",
            max_completion_tokens=500,
        )

        rag_context = join_blocks(
            [
                f"[{chunk['chunk_id']}] {chunk['text']}"
                for chunk in selected_top_chunks
            ],
            max_chars=18000,
        )
        rag_answer = groq_text_answer(
            groq_client,
            system_prompt="You are answering from retrieved chunks only. Cite chunk ids like [chunk_001] when you use them. Use plain ASCII only. Output only characters in the ASCII range 32-126 plus newline. Do not introduce diacritics, typographic quotes, Unicode dashes, special spaces, or transliterated spellings not present in the source text. Prefer simple spellings like Vyasa, Ganesa, Naimisha, and Mahabharata.",
            user_prompt=f"Question: {selected_question['question']}\n\nRetrieved chunks:\n{rag_context}",
            max_completion_tokens=500,
        )

    chunk_graphs, extraction_summary, graph_cache_hit = load_or_extract_chunk_graphs(
        groq_client,
        chunks,
        sample_text,
        config,
    )
    print(f"Graph extraction cache: {'hit' if graph_cache_hit else 'miss'}")

    graph = build_graph(chunk_graphs)
    graph_question_results: list[dict[str, Any]] = []
    for question in questions_to_run:
        question_vector = embedder.embed_query(question["question"])
        top_chunks = rank_chunks(chunks, question_vector, config.top_k)
        graph_ctx = graph_context(graph, chunk_graphs, top_chunks)

        print(f"Graph question {question['id']}: top chunks {[chunk['chunk_id'] for chunk in top_chunks]}")

        graph_context_text = join_blocks(
            [
                f"[{chunk['chunk_id']}] {chunk['text']}"
                for chunk in graph_ctx["related_chunks"][: config.top_k + 2]
            ],
            max_chars=14000,
        )
        entity_summary = "\n".join(
            f"- {entity['id']} ({entity['type']}): {entity['definition']}"
            for entity in graph_ctx["related_entities"][:12]
        )
        relation_summary = "\n".join(
            f"- {rel['source']} -[{rel['type']}]-> {rel['target']}: {rel['definition']}"
            for rel in graph_ctx["related_relationships"][:12]
        )
        graph_answer = groq_text_answer(
            groq_client,
            system_prompt="You are answering with graph-aware context. Use the retrieved passages, entities, and relationships. Cite chunk ids like [chunk_001] when possible. Use plain ASCII only. Output only characters in the ASCII range 32-126 plus newline. Do not introduce diacritics, typographic quotes, Unicode dashes, special spaces, or transliterated spellings not present in the source text. Prefer simple spellings like Vyasa, Ganesa, Naimisha, and Mahabharata.",
            user_prompt=(
                f"Question: {question['question']}\n\n"
                f"Retrieved passages:\n{graph_context_text}\n\n"
                f"Related entities:\n{entity_summary}\n\n"
                f"Related relationships:\n{relation_summary}"
            ),
            max_completion_tokens=550,
        )
        graph_question_results.append(
            {
                "question": question,
                "top_chunks": compact_chunk_view(top_chunks),
                "graph_rag": {
                    "answer": graph_answer["text"],
                    "usage": graph_answer["usage"],
                    "graph_node_count": graph.number_of_nodes(),
                    "graph_edge_count": graph.number_of_edges(),
                    "seed_chunk_ids": graph_ctx["seed_chunk_ids"],
                    "related_entity_count": len(graph_ctx["related_entities"]),
                    "related_relationship_count": len(graph_ctx["related_relationships"]),
                    "related_chunks": compact_chunk_view(graph_ctx["related_chunks"]),
                },
            }
        )

    nx_path = OUTPUT_DIR / "graph_edges.json"
    graph_edges = [
        {
            "source": source,
            "target": target,
            "type": attrs["type"],
            "definition": attrs["definition"],
            "chunk_id": attrs["chunk_id"],
        }
        for source, target, attrs in graph.edges(data=True)
    ]
    nx_path.write_text(json.dumps(graph_edges, indent=2), encoding="utf-8")

    nodes_path = OUTPUT_DIR / "graph_nodes.json"
    graph_nodes = [
        {
            "id": node_id,
            "type": attrs["type"],
            "definition": attrs["definition"],
            "chunk_ids": sorted(attrs["chunk_ids"]),
        }
        for node_id, attrs in graph.nodes(data=True)
    ]
    nodes_path.write_text(json.dumps(graph_nodes, indent=2), encoding="utf-8")

    extraction_path = OUTPUT_DIR / "chunk_extractions.json"
    extraction_path.write_text(json.dumps(chunk_graphs, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "config": {
            "groq_model": config.groq_model,
            "gemini_embedding_model": config.gemini_embedding_model,
            "embedding_backend": "Gemini API embeddings computed locally in Python",
            "graph_backend": "Local networkx graph built from Groq extraction output",
            "max_pages": config.max_pages,
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "top_k": config.top_k,
            "graph_only": config.graph_only,
            "all_questions": config.all_questions,
            "embedding_cache_hit": embedding_cache_hit,
            "graph_cache_hit": graph_cache_hit,
        },
        "sample_metadata": metadata,
        "chunk_count": len(chunks),
        "graph_stats": {
            "graph_node_count": graph.number_of_nodes(),
            "graph_edge_count": graph.number_of_edges(),
        },
        "extraction_summary": extraction_summary,
        "question_results": graph_question_results,
        "groq_call_log": groq_client.calls,
    }

    if not config.graph_only:
        result["question"] = selected_question
        result["top_chunks"] = compact_chunk_view(selected_top_chunks)
        result["simple_llm"] = llm_answer
        result["simple_rag"] = rag_answer
        result["graph_rag"] = graph_question_results[0]["graph_rag"]
        result_path = OUTPUT_DIR / "pilot_results.json"
    else:
        result_path = OUTPUT_DIR / "graph_only_results.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    LOGGER.info(
        "Pilot complete result_path=%s graph_nodes=%s graph_edges=%s groq_calls=%s",
        result_path,
        graph.number_of_nodes(),
        graph.number_of_edges(),
        len(groq_client.calls),
    )

    print(f"Saved pilot results to {result_path}")
    print(f"Saved graph nodes to {nodes_path}")
    print(f"Saved graph edges to {nx_path}")
    print(f"Saved chunk extraction details to {extraction_path}")
    print()
    if not config.graph_only and llm_answer and rag_answer:
        safe_print("Simple LLM answer:")
        safe_print(llm_answer["text"])
        safe_print()
        safe_print("Simple RAG answer:")
        safe_print(rag_answer["text"])
        safe_print()
    for question_result in graph_question_results:
        safe_print(f"GraphRAG-style answer for {question_result['question']['id']}:")
        safe_print(question_result["graph_rag"]["answer"])
        safe_print()


if __name__ == "__main__":
    main()
