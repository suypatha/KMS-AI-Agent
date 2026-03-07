from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "documents"
PROMPT_PATH = ROOT / "system_prompt.md"
VECTOR_STORE_PATH = ROOT / ".vector_store_id"

SUPPORTED_SUFFIXES = {
    ".c", ".cpp", ".cs", ".css", ".doc", ".docx", ".go", ".html", ".java",
    ".js", ".json", ".md", ".pdf", ".php", ".pptx", ".py", ".rb", ".sh",
    ".tex", ".ts", ".txt",
}


def load_config() -> tuple[OpenAI, str]:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
    model = os.getenv("OPENAI_MODEL", "gpt-5")
    return OpenAI(api_key=api_key), model


def read_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def find_documents() -> List[Path]:
    if not DOCS_DIR.exists():
        return []
    files = [p for p in DOCS_DIR.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    return sorted(files)


def save_vector_store_id(vector_store_id: str) -> None:
    VECTOR_STORE_PATH.write_text(vector_store_id, encoding="utf-8")


def get_vector_store_id() -> str | None:
    env_id = os.getenv("OPENAI_VECTOR_STORE_ID")
    if env_id:
        return env_id.strip()
    if VECTOR_STORE_PATH.exists():
        return VECTOR_STORE_PATH.read_text(encoding="utf-8").strip()
    return None


def create_or_replace_vector_store(client: OpenAI, files: Iterable[Path]) -> str:
    file_list = list(files)
    if not file_list:
        raise SystemExit("No supported files found in documents/.")

    vector_store = client.vector_stores.create(
        name="OCI KMS Advisor Documents",
        description="Internal OCI KMS documents for OCI KMS Advisor",
    )

    streams = []
    try:
        for path in file_list:
            streams.append(open(path, "rb"))
        batch = client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store.id,
            files=streams,
        )
    finally:
        for stream in streams:
            stream.close()

    if getattr(batch, "status", None) not in {"completed", "succeeded"}:
        raise SystemExit(f"Vector store upload did not complete successfully. Status: {getattr(batch, 'status', 'unknown')}")

    save_vector_store_id(vector_store.id)
    return vector_store.id


def persona_instructions(persona: str, stress_test: bool) -> str:
    if persona == "field":
        return (
            "Persona: Field Engineer / Sales. Keep the answer technically accurate, concise, and suitable for customer-facing use. "
            "Avoid internal-only roadmap details unless the user explicitly asks for an internal answer."
        )

    extra = ""
    if stress_test:
        extra = (
            " Enable PM argument stress-test mode: identify weak assumptions, missing evidence, risks, and stronger framing. "
            "Do not default to agreement."
        )

    return (
        "Persona: Product Manager. Optimize for analytical depth, structured comparison, and strategic clarity. "
        "Use tables when helpful for competitor comparisons or feature parity."
        + extra
    )


def ask_question(
    client: OpenAI,
    model: str,
    question: str,
    persona: str,
    enable_web: bool,
    stress_test: bool,
) -> str:
    vector_store_id = get_vector_store_id()
    if not vector_store_id:
        raise SystemExit("No vector store configured. Run 'python agent.py index' first.")

    tools = [
        {
            "type": "file_search",
            "vector_store_ids": [vector_store_id],
            "max_num_results": 8,
        }
    ]

    if enable_web:
        tools.append({"type": "web_search"})

    system_prompt = read_system_prompt()
    user_prompt = (
        f"{persona_instructions(persona, stress_test)}\n\n"
        "Follow the source priority strictly: uploaded internal documents first, then live web search, then model knowledge only if necessary and clearly labeled.\n\n"
        f"Question: {question}"
    )

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        tools=tools,
    )
    return response.output_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCI KMS Advisor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("index", help="Create a vector store and upload files from documents/")

    ask = subparsers.add_parser("ask", help="Ask a question")
    ask.add_argument("--persona", choices=["field", "pm"], default="field")
    ask.add_argument("--question", required=True)
    ask.add_argument("--no-web", action="store_true", help="Disable web search and use only uploaded docs + model knowledge")
    ask.add_argument("--stress-test", action="store_true", help="Enable PM argument stress-test behavior")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    client, model = load_config()

    if args.command == "index":
        docs = find_documents()
        vector_store_id = create_or_replace_vector_store(client, docs)
        print(f"Indexed {len(docs)} files into vector store: {vector_store_id}")
        return

    if args.command == "ask":
        answer = ask_question(
            client=client,
            model=model,
            question=args.question,
            persona=args.persona,
            enable_web=not args.no_web,
            stress_test=args.stress_test,
        )
        print(answer)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
