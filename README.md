# OCI KMS Advisor

OCI KMS Advisor is an internal AI assistant for OCI Key Management Service. It is built around the revised Agent Definition Document and uses an OpenAI-native stack for both build and runtime.

## What this repo contains

- `system_prompt.md` — the agent's core instructions
- `documents/` — uploaded context documents used for retrieval
- `agent.py` — a CLI app that indexes local documents into an OpenAI vector store and answers questions using the Responses API
- `requirements.txt` — Python dependencies
- `.env.example` — environment variable template

## Agent design

This implementation follows the revised definition document:
- agent name: OCI KMS Advisor
- users: Field Engineers, Sales, Product Managers
- purpose: answer OCI KMS capability and competitive intelligence questions
- source priority: uploaded internal docs, then live web search, then model knowledge
- required behavior: do not speculate, cite sources, and clearly state when reliable information is missing

## Prerequisites

- Python 3.10+
- An OpenAI API key
- A GitHub repository to push this project into

## Setup

1. Create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Create a `.env` file from `.env.example`.

```bash
cp .env.example .env
```

4. Set `OPENAI_API_KEY` in `.env`.

## Index local documents

This creates a vector store, uploads files from `documents/`, and saves the vector store ID in `.vector_store_id`.

```bash
python agent.py index
```

## Ask questions

### Field / Sales mode

```bash
python agent.py ask \
  --persona field \
  --question "Does OCI KMS support BYOK?"
```

### Product Manager mode

```bash
python agent.py ask \
  --persona pm \
  --question "Compare OCI KMS HSM options against AWS KMS, Azure Key Vault, Google Cloud KMS, and HashiCorp Vault."
```

### Disable web search

```bash
python agent.py ask \
  --persona pm \
  --no-web \
  --question "Summarize the uploaded KMS cost analysis and list the requested leadership decisions."
```

## Expected behavior

- The agent prioritizes uploaded internal documents over public web content.
- The agent uses web search for current public OCI and competitor facts.
- The agent states when it lacks enough reliable information.
- The agent avoids fabricated answers.

## Suggested document corpus

Add more files into `documents/` over time:
- OCI KMS feature sheets
- architecture docs
- service limits docs
- FAQ / approved field responses
- competitive battlecards
- compliance summaries
- internal roadmap notes approved for internal use

## Push to GitHub

This environment cannot push directly to your GitHub repository. Use these commands locally after copying or downloading this repo:

```bash
git init
git add .
git commit -m "Initial OCI KMS Advisor scaffold"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## Notes

- The current implementation is an MVP CLI, not a web app.
- The highest-risk failure mode is poor document hygiene. Keep the `documents/` folder curated and current.
- The strongest next step is to add eval questions and regression tests once your first batch of internal OCI documents is in place.
