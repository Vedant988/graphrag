import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
]
DEFAULT_SEQUENCE = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
]
RATE_HEADER_PREFIXES = (
    "x-ratelimit-",
    "retry-after",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a low-token Groq rate-limit experiment across models."
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file containing GROQ_API_KEY.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help="Models to mention in the summary. Sequence defaults are based on these model ids.",
    )
    parser.add_argument(
        "--sequence",
        nargs="+",
        default=DEFAULT_SEQUENCE,
        help="Exact ordered sequence of model ids to call.",
    )
    parser.add_argument(
        "--prompt",
        default="Reply with exactly the word ok.",
        help="Low-token prompt to send on each request.",
    )
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=8,
        help="Maximum completion tokens per request.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Delay between calls so header changes are easier to observe.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=45.0,
        help="Per-request timeout.",
    )
    parser.add_argument(
        "--output-jsonl",
        default="scripts/groq_rate_limit_experiment.jsonl",
        help="Where to append raw observations.",
    )
    return parser.parse_args()


def load_api_key(env_file: str) -> str:
    load_dotenv(env_file)
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(f"GROQ_API_KEY not found in {env_file}")
    return api_key


def extract_rate_headers(headers: requests.structures.CaseInsensitiveDict[str]) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower.startswith(RATE_HEADER_PREFIXES):
            extracted[lower] = value
    return extracted


def build_payload(model: str, prompt: str, max_completion_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
    }


def call_groq(
    session: requests.Session,
    api_key: str,
    model: str,
    prompt: str,
    max_completion_tokens: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    response = session.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=build_payload(model, prompt, max_completion_tokens),
        timeout=timeout_seconds,
    )
    finished = datetime.now(timezone.utc)

    record: dict[str, Any] = {
        "timestamp_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "elapsed_seconds": round((finished - started).total_seconds(), 3),
        "model": model,
        "status_code": response.status_code,
        "rate_headers": extract_rate_headers(response.headers),
    }

    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text}

    record["response_body"] = body

    if isinstance(body, dict):
        record["usage"] = body.get("usage")
        choices = body.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            record["assistant_text"] = message.get("content")
        if body.get("error"):
            record["error"] = body["error"]

    return record


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"models": {}, "calls": len(records)}
    for record in records:
        model_summary = summary["models"].setdefault(record["model"], [])
        model_summary.append(
            {
                "timestamp_utc": record["timestamp_utc"],
                "status_code": record["status_code"],
                "usage": record.get("usage"),
                "rate_headers": record.get("rate_headers", {}),
            }
        )
    return summary


def main() -> None:
    args = parse_args()
    api_key = load_api_key(args.env_file)

    output_path = Path(args.output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    session = requests.Session()

    for index, model in enumerate(args.sequence, start=1):
        record = call_groq(
            session=session,
            api_key=api_key,
            model=model,
            prompt=args.prompt,
            max_completion_tokens=args.max_completion_tokens,
            timeout_seconds=args.timeout_seconds,
        )
        record["call_index"] = index
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        records.append(record)

        print(
            json.dumps(
                {
                    "call_index": index,
                    "model": model,
                    "status_code": record["status_code"],
                    "usage": record.get("usage"),
                    "rate_headers": record.get("rate_headers", {}),
                },
                ensure_ascii=True,
            )
        )

        if index < len(args.sequence):
            time.sleep(args.sleep_seconds)

    print(json.dumps({"summary": summarize(records)}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
