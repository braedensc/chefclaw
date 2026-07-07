# Extractor robustness QA — image notes + media-resolution escalation

**Date:** 2026-07-07 · **Context:** V2-C part 2 (extractor-robustness half;
branch `feat/extractor-robustness-qa`). The mobile/PWA half of V2-C is a
separate session; this ADR covers only the extractor QA decisions. Builds on
[Source & extractor adapter contracts](2026-07-06-source-and-extractor-adapters.md).

## Decision

Two extractor changes plus a documented QA matrix (`docs/QA_MATRIX.md`):

1. **Image notes (图文) fast-fail with NO paid call** (option a of the plan). The
   Rednote adapter reads the sidecar's `作品类型` and, when it is an image note,
   raises the new typed `ImageNoteUnsupportedError` (`error_type =
   "image_note_unsupported"`, not retryable) **during the download stage —
   before any media download and before the paid model call.** A real
   multi-image→vision path (option b) is deferred to a named future ADR; it
   would spend on content the current video extractor can't read.

2. **One-shot media-resolution escalation, opt-in.** A new
   `GEMINI_MEDIA_RESOLUTION_MAX` (empty = OFF, the default) enables it. When set
   above the base `GEMINI_MEDIA_RESOLUTION`, the Gemini adapter uses a **v4
   envelope prompt** whose `capture_quality.on_screen_text` self-report lets the
   model flag overlay text it could not read at the base resolution; the adapter
   then **retries the same already-uploaded video once at the ceiling**, logs the
   escalation, and returns the richer read with **both calls' tokens summed into
   one spend row**. Escalation OFF ⇒ the shared v3 prompt and today's single-call
   behavior are unchanged byte-for-byte.

3. **Every `error_type` → clear, actionable jobs-drawer copy** (no bare
   "Error"/"Try again"), with a generic fallback for any future/unknown type.

## Why

- **Image notes, option (a) over (b):** the plan calls (a) "the cheap correct
  MVP+ answer." An image note reaches Gemini today as its first still frame and
  either fails typed or hallucinates a recipe from one photo — a paid call for
  guaranteed garbage. Detecting `作品类型` after the **free** metadata call, before
  the download and the paid call, spends nothing and gives the user a concrete
  fix ("paste a video post instead"). The full multi-image vision path is real
  work that SPENDS; it earns its own decision, not a drive-by.
- **Escalation trigger = model self-report, not a heuristic.** Every structural
  signal for "missed on-screen text" collides with a legitimate case: an empty
  array is a *non-cooking video*, null quantities are *适量 / genuinely
  unstated*. Only the model can honestly say "text was present but I couldn't
  read it." Carrying that as a `capture_quality` field in a tolerant envelope is
  the one honest trigger.
- **Rejected: changing the shared/default prompt.** The faithful-capture prompt
  is load-bearing (Hard Rule 7) and can't be A/B-validated without spend, and the
  Qwen fallback is *never exercised live*. So the v4 envelope is **Gemini-only and
  opt-in**: v3 stays the shared default for the no-escalation path and for Qwen,
  preserving the "same instructions for both backends" invariant in the default
  configuration. The parser is backward-tolerant (a bare array still parses), so
  even a non-compliant model can't break extraction.
- **Rejected: escalation on by default.** It changes the prompt *and* spends a
  second call. Cost discipline is a stated Hard-Rule-grade concern and the prompt
  is crown-jewel, so escalation ships wired + unit-tested but **default-off**,
  to be enabled after the paid QA run validates the v4 prompt empirically.
- **Accepted tradeoff — the escalation's 2nd paid call skips the worker's
  budget gate.** The worker checks budget once before `extract()`; the in-adapter
  retry doesn't re-check. This is bounded (at most one extra call per attempt,
  reusing the already-uploaded file — no re-upload), opt-in, and the summed usage
  keeps the ledger honest. The monthly budget is still checked before the attempt
  and the daily attempt cap still bounds total extractions. For a single-user
  app this is acceptable; a future move of escalation into the worker (a real
  pre-call budget gate per resolution step) is the graduation path if it ever
  runs by default.
- **Amends the adapters ADR's image-note "accepted tradeoff"** (which said the
  first media item becomes `video_path`): that path is now a typed fast-fail, not
  a silent first-frame upload. See the Update block appended there.

## Verified

- **Unit tier, no network/DB:** `uv run pytest tests/test_extractors.py
  tests/test_sources.py tests/test_worker.py` — image notes fast-fail with **no
  CDN download and no extractor call** (`test_rednote_fetch_image_note_fails_fast_without_download`,
  `test_image_note_is_terminal_without_a_paid_call`); escalation fires exactly
  once at the ceiling only on an `"unreadable"` report, sums usage, keeps the base
  result if the retry fails, tolerates a bare-array response, and fails closed on
  a non-higher/unknown ceiling (`test_gemini_escalates_once_when_text_unreadable`
  and siblings). Full backend unit tier green (see PR).
- **Frontend:** `npm test -w frontend` — every non-retryable `error_type`
  (including `image_note_unsupported`, `unsupported_url`, `validation_failed`)
  renders specific guidance and no Retry button; unknown types fall back to
  generic copy (`jobs-drawer.test.tsx`).
- **Real-video QA matrix** (`docs/QA_MATRIX.md`): run locally against a real
  Gemini key — flagged for spend, executed only after go-ahead — covering
  single/multi-dish, heavy on-screen-text (escalation), long video, 适量-heavy,
  deleted/expired URL, non-cooking (empty array), long-ingredient, both
  platforms, b23.tv + xhslink short links, and an image note. Each case's
  observed behavior is recorded there.
