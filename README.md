# Maia for PowerPoint – POC

A proof of concept for the three Phase 1 features in the Maia for PowerPoint proposal:

| Feature | What it does |
|---|---|
| **1.1 Summarise a deck** | Executive summary, key points, decisions, actions and open questions. Every point cites its slide numbers; citations to slides that don't exist are dropped. |
| **1.3 Speaker notes** | Notes per slide at a target length (130 words per minute), audience and tone. Existing notes are kept unless you choose to replace them. You review and edit, then download a **copy** of the deck with the notes. |
| **1.2 Prompt to deck** | The model drafts an outline as JSON; you review and edit it; the backend renders it with python-pptx onto **your template's own layouts** (.potx or .pptx). Optional source text grounds the deck. |

**Stack:** FastAPI backend, Streamlit UI, python-pptx, and the OpenAI SDK pointed at any OpenAI-compatible endpoint. It runs on OpenAI now; switching to the on-premise Qwen server is a change to `.env` only.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then set LLM_API_KEY

# Terminal 1: backend  (API docs at http://localhost:8000/docs)
uvicorn backend.main:app --reload --port 8000

# Terminal 2: UI  (opens http://localhost:8501)
streamlit run frontend/app.py
```

No API key yet? Set `LLM_PROVIDER=mock` to click through the whole flow with canned answers.

A sample deck for trying it out: `python scripts/make_sample_deck.py sample_deck.pptx`

## Switching to the on-premise Qwen

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://<qwen-server>/v1
LLM_MODEL=qwen3.6-35b-a3b
LLM_API_KEY=<token, or any non-empty string if the server has no auth>
```

If the server rejects `response_format`, set `LLM_JSON_MODE=false`; the backend still parses and validates the JSON and retries once on bad output.

## How it works

```
Streamlit UI ──HTTP──▶ FastAPI backend
                         ├─ /api/ppt/extract       .pptx → deck JSON (titles, text, tables, notes)
                         ├─ /api/ppt/summarise     deck JSON → cited summary
                         ├─ /api/ppt/notes         deck JSON → notes per slide
                         ├─ /api/ppt/notes/apply   .pptx + reviewed notes → copy with notes
                         ├─ /api/ppt/outline       prompt (+ source) → outline JSON + quality check
                         └─ /api/ppt/render        outline + template → new .pptx
                                   │
                         PII masking → prompt (content wrapped as untrusted) → LLM → JSON validated, one retry
```

- **Same deck JSON as the production design.** In production the VSTO plugin produces it; here the backend extracts it from the upload.
- **PII masking** (`backend/masking.py`): a regex stand-in for Maia's Phileas service; masks NRIC/FIN, SG phone numbers and email addresses before anything reaches the model. Turn off with `MASK_PII=false`.
- **Untrusted content:** deck and source text are wrapped in `<untrusted_deck>` / `<untrusted_source>` tags and the system prompt says never to follow instructions inside them.
- **Usage:** every response returns model, number of calls, tokens, LLM time and retries, shown in the UI, for the POC scorecard.
- **No storage:** files are processed in memory; logs record only method, path, status and time.

## Project layout

```
backend/
  main.py        FastAPI app and endpoints
  services.py    summarise, speaker notes, outline (no HTTP; scriptable)
  deck.py        extract, write notes, render outline on a template, outline quality check
  llm.py         OpenAI-compatible client, JSON validation and retry, mock provider
  prompts.py     prompt templates
  schemas.py     Pydantic models for requests, responses and LLM output
  masking.py     PII masking
  config.py      settings from environment / .env
frontend/app.py  Streamlit UI
scripts/make_sample_deck.py
tests/test_api.py   end-to-end tests with the mock model:  pytest -q
```

## POC limits (deliberate)

- **Public API:** while it runs on OpenAI, use **sanitised decks only**. The real data test happens after switching to Qwen.
- Not included: the PowerPoint plugin, async job queue, Redis, guardrail classifier, authentication, and Phase 2 features.
- Rendering uses each layout's title and body placeholders. Templates with unusual layout names fall back to the first, second and third layouts; check the result on the DSTA template.
- `.potx` templates are converted in memory (only a content type differs from `.pptx`); existing slides in a template are removed before rendering.

## Suggested POC evaluation

Run 10 sanitised decks through each feature and record, per deck:

| Measure | Target from the proposal |
|---|---|
| Summary faithfulness (no invented facts, reviewer check) | ≥ 95% |
| Points citing the correct slide | ≥ 95% |
| Outlines returned as valid JSON (`retries` = 0) | ≥ 99% |
| Generated slides flagged by the outline check | < 5% |
| Notes accepted without edits | ≥ 60% |
| Time and tokens per deck (from the usage panel) | Record for capacity planning |
