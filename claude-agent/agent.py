from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT.parent / "Documents"
PROMPT_PATH = ROOT.parent / "system_prompt.md"
FILE_IDS_PATH = ROOT / ".claude_file_ids.json"

# MIME types for all supported document extensions
MIME_MAP: Dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".json": "application/json",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".cs": "text/plain",
    ".go": "text/plain",
    ".rb": "text/plain",
    ".java": "text/plain",
    ".php": "text/plain",
    ".c": "text/plain",
    ".cpp": "text/plain",
    ".sh": "text/plain",
    ".tex": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# MIME types that Claude's document content blocks support natively
_DOCUMENT_MIMES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/html",
    "text/csv",
    "application/json",
}


def _is_document_mime(mime: str) -> bool:
    return mime in _DOCUMENT_MIMES or mime.startswith("text/")


def load_config() -> tuple[anthropic.Anthropic, str]:
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    return anthropic.Anthropic(api_key=api_key), model


def read_system_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise SystemExit(f"System prompt not found: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def find_documents() -> List[Path]:
    if not DOCS_DIR.exists():
        raise SystemExit(f"Documents directory not found: {DOCS_DIR}")
    return sorted(
        p for p in DOCS_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in MIME_MAP
    )


def index_documents(client: anthropic.Anthropic) -> None:
    docs = find_documents()
    if not docs:
        raise SystemExit("No supported files found in Documents/.")

    file_ids: Dict[str, str] = {}
    for path in docs:
        mime = MIME_MAP.get(path.suffix.lower(), "text/plain")
        print(f"  Uploading: {path.name} ({mime})...")
        try:
            with open(path, "rb") as f:
                uploaded = client.beta.files.upload(file=(path.name, f, mime))
            file_ids[path.name] = uploaded.id
            print(f"    -> {uploaded.id}")
        except Exception as exc:
            print(f"    [WARN] Skipped {path.name}: {exc}")

    FILE_IDS_PATH.write_text(json.dumps(file_ids, indent=2), encoding="utf-8")
    print(f"\nIndexed {len(file_ids)} file(s). IDs saved to {FILE_IDS_PATH.name}")


def load_file_ids() -> Dict[str, str]:
    if not FILE_IDS_PATH.exists():
        raise SystemExit("No indexed files found. Run 'python agent.py index' first.")
    return json.loads(FILE_IDS_PATH.read_text(encoding="utf-8"))


def build_document_blocks(file_ids: Dict[str, str]) -> list:
    """Build Anthropic content blocks for each uploaded file."""
    blocks = []
    for filename, file_id in file_ids.items():
        suffix = Path(filename).suffix.lower()
        mime = MIME_MAP.get(suffix, "text/plain")
        block: dict = {
            "type": "document",
            "source": {"type": "file", "file_id": file_id},
            "title": filename,
        }
        if _is_document_mime(mime):
            block["citations"] = {"enabled": True}
        blocks.append(block)
    return blocks


def persona_instructions(persona: str, stress_test: bool) -> str:
    if persona == "field":
        return (
            "Persona: Field Engineer / Sales. Keep the answer technically accurate, concise, and "
            "suitable for customer-facing use. Avoid internal-only roadmap details unless the user "
            "explicitly asks for an internal answer."
        )
    extra = (
        " Enable PM argument stress-test mode: identify weak assumptions, missing evidence, risks, "
        "and stronger framing. Do not default to agreement."
        if stress_test
        else ""
    )
    return (
        "Persona: Product Manager. Optimize for analytical depth, structured comparison, and "
        "strategic clarity. Use tables when helpful for competitor comparisons or feature parity."
        + extra
    )


def ask_question(
    client: anthropic.Anthropic,
    model: str,
    question: str,
    persona: str,
    enable_web: bool,
    stress_test: bool,
) -> str:
    file_ids = load_file_ids()
    system_prompt = read_system_prompt()

    user_text = (
        f"{persona_instructions(persona, stress_test)}\n\n"
        "Follow the source priority strictly: uploaded internal documents first, "
        "then live web search, then model knowledge only if necessary and clearly labeled.\n\n"
        f"Question: {question}"
    )

    # Build content: document blocks first, then the question text
    content: list = build_document_blocks(file_ids)
    content.append({"type": "text", "text": user_text})

    tools = (
        [{"type": "web_search_20260209", "name": "web_search"}]
        if enable_web
        else []
    )

    messages: list = [{"role": "user", "content": content}]
    betas = ["files-api-2025-04-14"]

    # Loop to handle pause_turn: occurs when a server-side tool loop hits its iteration limit
    response = None
    for _ in range(5):
        create_kwargs: dict = dict(
            model=model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=messages,
            betas=betas,
        )
        if tools:
            create_kwargs["tools"] = tools

        response = client.beta.messages.create(**create_kwargs)

        if response.stop_reason != "pause_turn":
            break

        # Server-side tool loop exceeded its limit — append assistant turn and continue
        # Do NOT add a new user message; the API detects the trailing server_tool_use block
        messages = messages + [{"role": "assistant", "content": response.content}]

    if response is None:
        return "No response generated."

    return next(
        (b.text for b in response.content if b.type == "text"),
        "No text in response.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCI KMS Advisor CLI — Claude Edition")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "index",
        help="Upload documents from Documents/ to Claude Files API",
    )

    ask = subparsers.add_parser("ask", help="Ask a question")
    ask.add_argument("--persona", choices=["field", "pm"], default="field")
    ask.add_argument("--question", required=True)
    ask.add_argument(
        "--no-web",
        action="store_true",
        help="Disable web search — use only uploaded docs and model knowledge",
    )
    ask.add_argument(
        "--stress-test",
        action="store_true",
        help="Enable PM argument stress-test mode (effective with --persona pm)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    client, model = load_config()

    if args.command == "index":
        index_documents(client)
    elif args.command == "ask":
        print(
            ask_question(
                client=client,
                model=model,
                question=args.question,
                persona=args.persona,
                enable_web=not args.no_web,
                stress_test=args.stress_test,
            )
        )
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
