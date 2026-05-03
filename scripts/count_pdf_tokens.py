import argparse
import json
from pathlib import Path

import tiktoken
from pypdf import PdfReader


def resolve_encoding(model_name: str | None, encoding_name: str | None) -> tiktoken.Encoding:
    if model_name:
        try:
            return tiktoken.encoding_for_model(model_name)
        except Exception:
            pass

    if encoding_name:
        return tiktoken.get_encoding(encoding_name)

    return tiktoken.get_encoding("cl100k_base")


def count_pdf_tokens(pdf_path: Path, model_name: str | None, encoding_name: str | None) -> dict:
    encoding = resolve_encoding(model_name, encoding_name)
    reader = PdfReader(str(pdf_path))

    page_texts: list[str] = []
    total_chars = 0
    total_words = 0
    total_tokens_by_page = 0
    empty_pages = 0
    min_page_tokens = None
    max_page_tokens = 0

    for page in reader.pages:
        text = page.extract_text() or ""
        page_texts.append(text)
        total_chars += len(text)
        total_words += len(text.split())

        if not text.strip():
            empty_pages += 1

        page_tokens = len(encoding.encode(text))
        total_tokens_by_page += page_tokens
        min_page_tokens = page_tokens if min_page_tokens is None else min(min_page_tokens, page_tokens)
        max_page_tokens = max(max_page_tokens, page_tokens)

    joined_text = "\n".join(page_texts)
    joined_tokens = len(encoding.encode(joined_text))

    return {
        "pdf_path": str(pdf_path),
        "pages": len(reader.pages),
        "empty_pages": empty_pages,
        "chars": total_chars,
        "words": total_words,
        "encoding": encoding.name,
        "tokens_sum_pages": total_tokens_by_page,
        "tokens_joined_document": joined_tokens,
        "avg_tokens_per_page": round(total_tokens_by_page / len(reader.pages), 2) if reader.pages else 0,
        "min_page_tokens": min_page_tokens,
        "max_page_tokens": max_page_tokens,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a PDF and count tokens.")
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF file")
    parser.add_argument(
        "--model",
        dest="model_name",
        help="Optional model name for tokenizer selection, for example text-embedding-3-small",
    )
    parser.add_argument(
        "--encoding",
        dest="encoding_name",
        default="cl100k_base",
        help="Fallback encoding name when model resolution is unavailable",
    )
    args = parser.parse_args()

    stats = count_pdf_tokens(args.pdf_path, args.model_name, args.encoding_name)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
