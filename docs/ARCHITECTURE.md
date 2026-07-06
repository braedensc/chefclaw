# Architecture

chefclaw: paste a Bilibili or Rednote cooking-video link → async extraction
pipeline → structured bilingual recipe in a browsable library. Single user now,
deploy-ready by design. Four rules shape every layer:

1. **The API is the product; the UI is a client.** The REST/OpenAPI surface is
   the stable contract. The SPA is its first client; an MCP server and mobile
   arrive later as further clients of the same API.
2. **Framework-free service layer.** All business logic lives in plain Python
   services. FastAPI routers are one thin transport (parse/validate/serialize
   only); no logic in routers or React.
3. **Everything external is an adapter.** Video sources (`SourceAdapter`),
   extraction models (`ExtractorAdapter`), and later nutrition/fitness/price
   providers sit behind small, documented interfaces. Adding a platform is a
   new adapter, not a refactor.
4. **Anything slow is an async job.** Extraction takes minutes; requests never
   block on it. A `jobs` table in Postgres claimed with `FOR UPDATE SKIP
   LOCKED`, executed strictly serially by an in-process worker — no broker.

Plus the product invariant (CLAUDE.md Hard Rule): **never fabricate food data**
— quantities captured verbatim from the source; estimated or derived values
live in separate, explicitly-flagged fields and never overwrite raw captures.

Decisions are recorded as ADRs in `docs/adr/` — one file per decision, named
`YYYY-MM-DD-short-slug.md`, no sequence numbers (convention:
[docs/adr/README.md](adr/README.md)). This table is the index; adding an ADR
adds one row here.

## Index

| ADR | Date | Decision |
|---|---|---|
| [MVP stack & layout](adr/2026-07-05-mvp-stack-and-layout.md) | 2026-07-05 | Python 3.13 + FastAPI + Postgres 18; no-broker single-worker async jobs; Vite + React SPA served same-origin; npm-workspaces monorepo; exact-pins policy |
| [AGPL licensing & kit attribution](adr/2026-07-05-agpl-licensing-and-kit-attribution.md) | 2026-07-05 | AGPL-3.0-or-later (dual-license optionality, sole copyright holder); kit's MIT license preserved in NOTICE |
| [Source & extractor adapter contracts](adr/2026-07-06-source-and-extractor-adapters.md) | 2026-07-06 | `SourceAdapter` resolve → `CanonicalRef` as the authoritative dedupe input; rednote guest-tier default + accepted `xsec_token` fetch-url deviation; digest-pinned internal-only XHS sidecar with per-request cookie; extractor never repairs output; fakes config-selectable |
| [Jobs without a broker](adr/2026-07-06-jobs-without-broker.md) | 2026-07-06 | In-process asyncio worker (one uvicorn worker, strictly serial — double-spend closed at concurrency 1); `FOR UPDATE SKIP LOCKED` claim with attempts counted at claim; idempotent paid stage + fail-closed budget gate before every paid call + per-attempt spend ledger; startup reconcile to `interrupted` (never auto-rerun paid work); atomic N-recipe store; TaskIQ as graduation path |
| [Data model & dedupe on canonical identity](adr/2026-07-06-data-model-and-dedupe.md) | 2026-07-06 | `UNIQUE(platform, canonical_id, dish_index)` as THE dedupe constraint (canonical identity, never raw URLs); `owner_id` + uuidv7 pks from migration #1; jobs carry queryable platform/canonical_id + payload `url`/`fetch_url` (retries never re-resolve); `llm_spend` per attempt as cost/cap source of truth; hard DELETE re-opens extraction; `document` JSONB never user-editable |

## Planned ADRs

Reserved here so deferrals stay decisions, not accidents. Each is written when
its phase or milestone opens, with a design pass over
`planning/chefclaw-plan.md` (gitignored reference) first.

**Phase 2 — extraction pipeline:**

- **Adapter contracts, sidecar isolation & extractor config** — **done**:
  [Source & extractor adapter contracts](adr/2026-07-06-source-and-extractor-adapters.md)
  (2026-07-06) covers the `SourceAdapter`/`ExtractorAdapter` interfaces,
  canonical-id resolution, rednote tiered access, the digest-pinned
  internal-only XHS sidecar, and the Gemini extractor settings.
  DashScope/Qwen fallback and the degraded ASR+OCR roadmap keep their Phase-4
  slot (docs/SERVICES.md §3).
- **Jobs without a broker** — **done**:
  [Jobs without a broker](adr/2026-07-06-jobs-without-broker.md) (2026-07-06)
  covers the full worker semantics as shipped — idempotent paid stage,
  attempt caps, startup reconcile, fail-closed budget guardrails, the
  per-attempt spend ledger, the atomic N-recipe store, the two hard
  constraints (one uvicorn worker, strictly serial execution), and the TaskIQ
  graduation path. Process-group kill stays a noted follow-up there
  (cooperative thread cancellation is the accepted tradeoff).
- **Data-model shape** — **done**:
  [Data model & dedupe on canonical identity](adr/2026-07-06-data-model-and-dedupe.md)
  (2026-07-06) covers recipes/jobs/llm_spend as exercised, dedupe on
  canonical identity via `UNIQUE(platform, canonical_id, dish_index)`, the
  job payload's `url`/`fetch_url` split, hard-delete-reopens-extraction, and
  the never-user-editable JSONB document.

**Future — explicitly reserved:**

- **Re-extraction semantics** — what happens when a stored recipe's source is
  extracted again (prompt v2, resolution escalation, model swap). Deferred at
  MVP (DELETE is a hard delete; a duplicate paste returns the existing job);
  this entry exists so the deferral cannot fall through the cracks. Must
  address stale rednote `xsec_token` fetch_urls (tokens expire, so
  re-extraction may need a fresh share link — see the 2026-07-06 adapters
  ADR's accepted tradeoffs) and the partial multi-dish delete quirk
  (deleting one of N sibling recipes leaves the rest, so dedupe still
  returns the stored job and the deleted dish is not re-extractable — see
  the 2026-07-06 data-model ADR's accepted tradeoffs).

**Milestones — each opens with its own ADR:**
M-Deploy (Tailscale-first; the datacenter-IP/Rednote wrinkle) · M5 nutrition ·
M6 meal planning + grocery · M7 fitness ingestion · M8 MCP server · M9 mobile.
