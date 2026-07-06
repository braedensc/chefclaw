# Source & extractor adapter contracts

**Date:** 2026-07-06 · **Context:** Phase 2 — extraction pipeline (branch
`feat/extraction-adapters`; facts below verified in real spikes, 2026-07-06)

## Decision

Phase 2's adapter layer is two small interfaces. **`SourceAdapter`**
(`matches` / `resolve` / `fetch`): `resolve()` returns
`CanonicalRef(platform, canonical_id, fetch_url)` and is the **authoritative dedupe
input** — dedupe keys on canonical identity, never on raw URLs (plan amendment §16.1).
**`ExtractorAdapter`**: `extract(video_path, title, duration)` → raw dish dicts +
usage (tokens, model id, prompt v1). `FakeSource` / `FakeExtractor` are first-class,
config-selectable adapters (tests + the golden suite), not ad-hoc test doubles.

### Canonical identity (per platform)

| Platform | `canonical_id` | Notes |
|---|---|---|
| bilibili | `BVxxx-pN` | `?p=` is semantic (part number), kept; tracking params stripped |
| rednote | bare 24-hex note id | token-free — see accepted tradeoffs |
| local | `file-<sha256[:16]>` | content-addressed (`LocalFileSource`, the tier-2 upload floor) |

`resolve()` may follow short-link redirects (`b23.tv`, `xhslink.com`). A
`list_saved()` capability slot is **documented-reserved, unimplemented**
(saved-collections import comes later, behind its own ADR).

### Rednote — tiered access + sidecar contract

Shipped per the access policy (plan §16.10): **guest tier is the default** and is
verified working. A cookie is tier-1 only (hard-isolated throwaway account, never the
main account) and rides **per-request** in the sidecar API call from the api's env —
the sidecar stays stateless; **no config-file cookie mount**. The sidecar echoes the
cookie back in its `params` field, so the adapter parses only `data` and **raw
sidecar response bodies must never be logged**.

Sidecar isolation: `joeanamier/xhs-downloader` pinned to digest
`sha256:7ce9c4e7711b7a805da5b1d4190079ad0eaf4abf07f235fe8b90c8da51b8c823`
(v2.7.stable), command `python main.py api`, port 5556, **compose-internal only — no
published port** (the API is unauthenticated). Contract:
`POST /xhs/detail {url, download:false, cookie?}` → `{message, params, data}`. The
api downloads the returned media URLs itself, keeping scratch + retention in one
place.

### Bilibili

yt-dlp, **anonymous-first, 480p cap**; optional cookie only to raise resolution.
DASH merge requires **ffmpeg in the api image**.

### Extractor rules

The extractor **never validates or repairs output** (Hard Rule 7); the documents
layer validates strictly and preserves raw output on failure. Gemini: Files API,
`thinking_budget=0`, `temperature=0.1`, `media_resolution` from config (escalate only
if overlay text is missed), model id from config. **No internal retries** — the
worker owns attempts and runs budget checks before every paid call.

## Why

- Raw URLs cannot dedupe (short links, tracking params, per-share `xsec_token`);
  canonical identity can. Making `resolve()` the single authority keeps the
  paid-call dedupe gate honest.
- Per-request cookie beats a mounted cookie file: the sidecar holds no credentials
  at rest, and one place (the api's env) owns the secret.
- `response_schema` constrained decoding was **rejected by name**: it silently drops
  and coerces fields — quiet repair, exactly what Hard Rule 7 forbids. Strict
  post-hoc validation preserves the raw evidence instead.

## Accepted tradeoffs

- **`xsec_token` deviation (accepted):** the plan's intent was fetch-by-note-id, but
  Xiaohongshu rejects token-less URLs (verified against XHS-Downloader v2.7 — bare
  note-id URLs always fail). `fetch_url` therefore preserves the pasted share link's
  `xsec_token` (that param only); `canonical_id` stays token-free, so dedupe is
  intact. **Corollary for the reserved re-extraction ADR:** stored rednote
  `fetch_url`s go stale as tokens expire — re-extraction may need a fresh share link.
- **Legacy Bilibili av-ids are deliberately unsupported** (`UnsupportedUrlError`) —
  a decision, not a gap.
- **Image notes (图文):** the first media item becomes `video_path`; all media is
  preserved in `extra`.

## Verified (2026-07-06, real spikes)

- **Rednote guest tier works:** a real public note fetched with **no cookie**.
- **Token requirement is real:** bare note-id URLs always fail against
  XHS-Downloader v2.7; full share links (with `xsec_token`) succeed.
- **Bilibili end-to-end:** yt-dlp anonymous 480p verified including the DASH merge
  (which is what forces ffmpeg into the api image).
