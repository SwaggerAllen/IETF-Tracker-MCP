# Working Group Activity Tracker — Implementation Plan

> Status: **proposed**, pending review. This document captures the architecture and
> decisions for building the IETF Working Group Activity Tracker described in the build
> spec. It is the review artifact before implementation begins.

## 1. What we're building (recap)

A **structured archive** for tracking IETF working group consensus and activity over
time — a Postgres database of thread-level LLM summaries, organized by date, working
group, topic, and **cross-referenced to the IETF drafts being discussed**, with every
summary linking back to its source thread for one-click verification.

This is deliberately **not** a vector/RAG tool. The access pattern is "organized history
of topic X" and "what's happened recently," which are structured range/filter queries.
Verifiability (source URLs on every claim) and bounded per-thread LLM work are first-class
requirements. See the build spec for the full rationale; this plan does not re-litigate it.

## 2. Decision log (settled in planning)

| # | Decision | Choice | Notes |
|---|----------|--------|-------|
| D1 | Language | **Python** backend | Mail/MIME/mbox parsing via stdlib `email`/`mailbox` is the hardened core; matches spec's SQLAlchemy/Alembic assumptions; pydantic validates LLM JSON outputs. |
| D2 | Debug UI | **React SPA** (Vite + TypeScript), **read + re-trigger** | Not server-rendered. Consumes a JSON API. Can re-trigger pipeline stages, not just view. |
| D3 | UI serving | **Same-origin**: FastAPI serves the built SPA bundle | No CORS, single Basic-auth boundary. Alternative (DO Static Site + cross-origin token auth) noted but not chosen. |
| D4 | MCP server | **Remote on DO**, over **HTTP** (Streamable HTTP transport), bearer-token auth | Per spec's open question; user chose remote. |
| D5 | Component consolidation | Debug UI API + MCP HTTP + `/health` share **one Web Service** | Two routers, different auth. Avoids paying for two always-on instances on a single-user budget. |
| D6 | Scheduling | **Deferred** — designed as a swappable trigger | Default APScheduler-in-worker; external trigger (GitHub Actions / DO Function) is a thin swap. Locked at deploy step. |
| D7 | Live external verification | **Blocked in this environment** | Session network policy denies `*.ietf.org` (`403 host_not_allowed`). Clients coded against documented formats; real-archive validation happens at DO runtime / locally. |

## 3. Architecture — DigitalOcean App Platform

```
                          ┌─────────────────────────────────────────┐
                          │        DO App Platform (one App)          │
                          │                                           │
  Claude Desktop/Code ───▶│  ┌─────────────┐   MCP-over-HTTP (bearer) │
  (MCP client)            │  │             │                         │
                          │  │  api        │   /mcp        ─┐         │
  Browser (you) ─────────▶│  │  Web Service│   /api/*  ────┼─ Basic  │
                          │  │  (FastAPI)  │   / (SPA)  ───┘  auth    │
                          │  │             │   /health (open)        │
                          │  └──────┬──────┘                         │
                          │         │                                │
                          │  ┌──────▼──────┐   reads/writes          │
                          │  │  worker     │   - APScheduler loop    │
                          │  │  (Worker)   │   - batch submit/poll   │
                          │  └──────┬──────┘   - ingestion+pipeline  │
                          │         │                                │
                          │  ┌──────▼──────┐                         │
                          │  │  db         │   Managed PostgreSQL    │
                          │  └─────────────┘                         │
                          │                                           │
                          │  migrate (Job, PRE_DEPLOY): alembic upgrade│
                          └─────────────────────────────────────────┘
                                    │ outbound (runtime only)
                                    ▼
                  mailarchive.ietf.org  +  datatracker.ietf.org
```

| Component | App Platform type | Responsibility |
|-----------|-------------------|----------------|
| `api` | Web Service | Serves React SPA (static), JSON API for the UI, MCP-over-HTTP, `/health`. |
| `worker` | Worker | Pipeline orchestration: ingestion, cleaning, draft sync, batch submit/poll, summarization, categorization. Houses the scheduler. |
| `migrate` | Job (PRE_DEPLOY) | `alembic upgrade head` before each deploy. |
| `db` | Managed Postgres | All storage. |
| `web` (SPA) | *(folded into `api`)* | Built bundle copied into `api` image; not a separate component (D3/D5). |

## 4. Tech stack

- **Python 3.12**, `pyproject.toml`, `uv` or `pip` for deps.
- **FastAPI** + **uvicorn** — JSON API, MCP HTTP transport, static serving, health check.
- **SQLAlchemy 2.x** (typed ORM) + **Alembic** (migrations). Postgres-native: JSONB,
  `tsvector` full-text indexes, real FKs with cascades, indexes on
  `working_group` / `last_activity_date` / `topic_id`.
- **pydantic v2** + **pydantic-settings** — config + env, and validation of LLM
  structured outputs before they hit JSONB columns.
- **anthropic** SDK — Message Batches API for all summarization/categorization.
- **mcp** (official Python SDK) — Streamable HTTP server transport.
- Stdlib **`email`** + **`mailbox`** — RFC 5322 / MIME / mbox parsing.
- **httpx** (with retry/backoff) — mailarchive export + datatracker clients.
- **APScheduler** — in-worker scheduling (swappable per D6).
- **structlog** — structured JSON logs to stdout (App Platform aggregates).
- **Frontend**: **Vite + React + TypeScript**, minimal component set, fetches the JSON API.

## 5. Repository layout

```
.
├── PLAN.md                      # this file
├── README.md
├── pyproject.toml
├── config.yaml                  # application config (non-secret)
├── alembic.ini
├── Dockerfile                   # multi-stage: node(SPA build) → python(runtime)
├── .do/app.yaml                 # App Platform spec (components, jobs, db)
├── migrations/                  # alembic
│   └── versions/
├── src/wgtracker/
│   ├── config.py                # YAML + env loading (pydantic-settings)
│   ├── logging.py               # structlog JSON setup
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models (all tables)
│   │   └── session.py
│   ├── ingest/
│   │   ├── mailarchive.py       # mbox export client (httpx + retry)
│   │   ├── parse.py             # RFC 5322 / MIME parsing, encoding-safe
│   │   ├── threads.py           # thread reconstruction (References/In-Reply-To + fallback)
│   │   └── clean.py             # quote + signature stripping
│   ├── drafts/
│   │   ├── extract.py           # regex extraction (all 5 reference forms)
│   │   └── datatracker.py       # datatracker API client + sync strategy
│   ├── llm/
│   │   ├── batch.py             # batch submit/poll/retrieve, idempotency
│   │   ├── summarize.py         # Sonnet 4.6 thread summarization
│   │   ├── categorize.py        # Haiku 4.5 categorization + admin pre-filter
│   │   ├── prompts.py           # prompt templates (consensus-careful language)
│   │   └── cost.py              # token/cost logging → processing_log
│   ├── pipeline.py              # stage orchestration + scheduler entrypoints
│   ├── queries.py               # shared query layer (used by CLI, API, MCP)
│   ├── cli.py                   # the v1 query/admin CLI
│   ├── api/
│   │   ├── app.py               # FastAPI app, auth, static mount, /health
│   │   ├── routes_ui.py         # JSON API for the SPA (incl. re-trigger)
│   │   └── routes_mcp.py        # MCP-over-HTTP
│   └── mcp_server/
│       └── tools.py             # MCP tool definitions (search_threads, etc.)
└── frontend/                    # Vite + React + TS SPA
    ├── package.json
    └── src/
```

## 6. Data model

Implemented exactly as specified: `threads`, `messages`, `topics`, `thread_topics`,
`drafts`, `thread_drafts`, `processing_log`. Postgres-native choices:

- **Enums** as Postgres `ENUM` types: `thread.status` (active/concluded/abandoned),
  `thread.consensus_state` (clear_consensus / emerging_consensus / active_debate /
  no_consensus / single_voice).
- **JSONB** for `key_positions`, `participants`, `keywords`, `authors`, `versions`,
  `references`, `versions_referenced`.
- **FKs** with `ON DELETE CASCADE` for `messages→threads`, `thread_topics`,
  `thread_drafts`.
- **Indexes**: `threads(working_group)`, `threads(last_activity_date)`,
  `threads(subject)`, `messages(thread_id)`, `messages(from_address)`,
  `drafts(working_group)`, `thread_topics(topic_id)`, `processing_log(date)`.
- **Full-text**: a generated `tsvector` column on `threads` (subject + summary) with a
  GIN index, for the CLI/UI text filter (this is FTS, *not* vector search).
- A small **`batch_jobs`** table (addition) to track async Anthropic batch submissions
  (batch_id, stage, status, submitted_at, item count) so the worker can poll and resume
  idempotently across runs.

## 7. Pipeline stages (and the async-batch shape)

Stages 1–6 per spec. The key architectural refinement: **the Batch API is asynchronous
(up to ~24h)**, so the pipeline is **submit → persist batch id → poll → retrieve**, never
a single blocking run.

```
ingest → reconstruct threads → clean → extract draft refs → sync draft metadata
   → [submit summarization batch]  ──persist batch_jobs──┐
   → [submit categorization batch] ──persist batch_jobs──┤
                                                          ▼
                          (later worker tick) poll batches → retrieve → write results
```

- **Idempotency**: dedupe messages by `Message-ID`; re-summarize a thread only if
  `last_activity_date > thread.last_processed`; re-categorize cheaply when the taxonomy
  changes (no re-summarization).
- **Admin pre-filter** (Haiku) flags meeting-reminder / bot / "+1" threads to skip
  summarization spend.
- **Cost tracking**: every LLM call logs input/output tokens, model, stage, and
  estimated cost to `processing_log`; CLI + UI surface spend by stage. Budget guardrails
  per spec ($200 ceiling; backfill $20–50; ongoing ~$15/yr) — the worker refuses to
  exceed configured caps without an explicit override flag.
- **Failure handling**: archive unavailable → retry w/ backoff, log, continue; LLM errors
  → retry, log, skip thread; malformed messages → skip + log, never crash; broken thread
  roots → subject + time-proximity heuristic fallback.

## 8. External integrations (documented formats; runtime-validated)

> ⚠️ Per D7, these could not be probed live from this build environment
> (`403 host_not_allowed` for `*.ietf.org`). Clients are written against documented
> formats and will be validated against the real archive at DO runtime / on your machine.

- **Mail archive**: mbox export `GET https://mailarchive.ietf.org/arch/export/mbox/?email_list=<wg>`
  (date-range parameters applied where supported to fetch only new mail; otherwise fetch
  + dedupe by Message-ID). Per-message permalink `archive_url` pattern
  `https://mailarchive.ietf.org/arch/msg/<list>/<hash>/`. mbox gives real RFC 5322 headers
  for thread reconstruction.
- **Datatracker**: Tastypie JSON at `https://datatracker.ietf.org/api/v1/` —
  `doc/document/?name=<draft>&format=json` (metadata, rev, abstract, states),
  `doc/docalias/?name=<draft>` (renames/RFC mapping), `doc/dochistory/?name=<draft>`
  (versions). Draft text deep-links: `https://www.ietf.org/archive/id/<draft>-<ver>.{txt,html}`.
- **Draft reference extraction** catches all five forms: bare `draft-…`, versioned
  `draft-…-NN`, `RFC NNNN`, datatracker URLs, archived-id URLs. Version-specificity is
  preserved (discussing `-03` ≠ `-04`).

## 9. LLM usage

- **Summarization**: Sonnet 4.6 (`claude-sonnet-4-6`) via Batch API. Prompt includes
  cleaned thread + **referenced-draft metadata** (name, current version, title, abstract,
  version(s) discussed) so summaries are *about* the drafts, not just mentions. Full draft
  text is **not** included.
- **Categorization + admin pre-filter**: Haiku 4.5 (`claude-haiku-4-5`) via Batch API.
- **Consensus discipline**: prompts forbid "the WG decided X" without clear signal;
  require attributed language ("Position X advocated by [name], [name] raised [concern]")
  and force selection of a `consensus_state`. Outputs validated with pydantic before write.

## 10. Debug UI (React SPA)

Read + re-trigger (D2). Views: pipeline/batch status dashboard, thread list (filter by
WG/topic/date/status) → thread detail (summary, key positions, consensus state,
participants, referenced drafts, **source link**), draft list/detail, cost-by-stage,
processing log/errors. Re-trigger actions (ingest / summarize / recategorize) **enqueue**
work (write a `batch_jobs`/log row) for the worker to pick up — they don't block the HTTP
request, consistent with async batch. Served same-origin behind Basic auth (D3).

## 11. MCP server (remote HTTP)

Streamable-HTTP MCP at `/mcp` on the `api` service, **bearer-token** auth (D4). Tools per
spec: `search_threads`, `get_thread_detail`, `recent_activity`, `topic_overview`,
`list_drafts`, `get_draft`, `draft_discussion_history`. **Every** tool that returns a
summary also returns the **source `archive_url`** so Claude can cite it. All tools are thin
wrappers over the shared `queries.py` layer (same code path as the CLI and UI).

## 12. Config & secrets

- `config.yaml` (non-secret): `working_groups`, `topics` (name/description/keywords),
  `llm` (model ids, `use_batch_api`), `processing` (thresholds, flags), `drafts`
  (datatracker base, refresh policy). Editable; topic changes trigger recategorization.
- **Env** (DO App Platform): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CONFIG_PATH`,
  `LOG_LEVEL`, plus `UI_BASIC_AUTH_USER`/`UI_BASIC_AUTH_PASS` and `MCP_BEARER_TOKEN`
  (auth, added for the remote-exposure decisions D2/D4), and `COST_CEILING_USD`.

## 13. Build milestones

**Milestone 1 — verifiable, zero API cost** (stop for your spot-check):
1. Scaffold (pyproject, config loader, structlog, settings).
2. Schema + Alembic migrations (all tables + `batch_jobs`).
3. Ingestion: mbox export client + RFC 5322/MIME parse + dedupe.
4. Thread reconstruction (+ heuristic fallback).
5. Message cleaning (quote/signature stripping).
6. Draft reference extraction + datatracker metadata sync.
7. Sanity CLI (`list threads`, `show thread`, `drafts`).

→ **You verify** threads reconstruct correctly and `archive_url`s resolve. No LLM yet.

**Milestone 2 — LLM + interfaces + deploy:**
8. Summarization (Sonnet 4.6, Batch, draft-aware) + cost tracking.
9. Categorization + admin pre-filter (Haiku 4.5, Batch).
10. Full CLI query interface.

→ **You spot-check** summaries on a small MLS sample (accuracy, citations, categorization, cost vs. estimate).

11. MCP HTTP server (7 tools, source URLs always).
12. React SPA debug UI (read + re-trigger).
13. Dockerfile (multi-stage) + `.do/app.yaml` + lock scheduling mechanism (D6).
14. Deploy to DO App Platform; validate small sample end-to-end.
15. Full backfill of configured WGs (only after validation; within budget).

## 14. Open questions / risks

1. **Scheduling mechanism (D6)** — confirm APScheduler-in-worker vs. external trigger at step 13.
2. **mbox export incremental fetch** — whether the export endpoint supports server-side
   date filtering, or we always fetch + dedupe. Resolved at runtime validation (D7).
3. **Datatracker field mapping** — exact field names for state/RFC-number; verified at
   runtime, with defensive parsing meanwhile.
4. **Budget guardrail behavior** — confirm the worker should hard-stop at `COST_CEILING_USD`
   and require an explicit override to continue.
5. **DB connection limits** — managed Postgres connection caps vs. worker + api concurrency;
   may need a pooler (PgBouncer / SQLAlchemy pool tuning) at deploy.
