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
- **Jobs without a broker** *(next PR)* — full worker semantics (idempotent
  stages, attempt caps, startup reconcile, process-group kill; the multi-dish
  N-recipe insert and the job's flip to `stored` commit in one database
  transaction), fail-closed budget guardrails and the per-attempt spend
  ledger, and the two hard constraints of the design: exactly one uvicorn
  worker process, strictly serial job execution; graduation path (TaskIQ).
- **Data-model shape** *(next PR)* — recipes/jobs/llm_spend, the JSONB recipe
  document, and dedupe on canonical identity: `SourceAdapter` resolves
  platform + native id, `UNIQUE(platform, canonical_id, dish_index)`, raw
  pasted URL kept as provenance only, canonical-id check gating the paid
  model call.

**Future — explicitly reserved:**

- **Re-extraction semantics** — what happens when a stored recipe's source is
  extracted again (prompt v2, resolution escalation, model swap). Deferred at
  MVP (DELETE is a hard delete; a duplicate paste returns the existing job);
  this entry exists so the deferral cannot fall through the cracks. Must
  address stale rednote `xsec_token` fetch_urls (tokens expire, so
  re-extraction may need a fresh share link — see the 2026-07-06 adapters
  ADR's accepted tradeoffs).

**Milestones — each opens with its own ADR:**
M-Deploy (Tailscale-first; the datacenter-IP/Rednote wrinkle) · M5 nutrition ·
M6 meal planning + grocery · M7 fitness ingestion · M8 MCP server · M9 mobile.
