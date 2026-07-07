# Extractor QA matrix

The "variety of cases, no bugs" proof for the paste→recipe pipeline (V2-C part 2,
plan §V2-C · ADR [extractor-robustness-qa](adr/2026-07-07-extractor-robustness-qa.md)).
Each row is a real-world shape the extractor must handle; the table records what
the pipeline is **expected** to do and the **observed** result of running it.

Two tiers of case:

- **Free** — no paid model call (typed pre-extraction failures, short-link
  resolution, image-note fast-fail). Reproducible in unit tests and/or against
  the stack with `CHEFCLAW_EXTRACTOR=fake`.
- **Paid** — a real Gemini extraction. Each run **spends a few cents of Gemini
  quota.** Flag the spend and get a go-ahead before running the paid rows
  (Hard-rule cost discipline). See _Running the paid cases_ below.

## Running the paid cases (local only — never CI)

The paid rows need the real stack with a real key. This is **local only** and
uses Braeden's Gemini key.

1. Human precondition: `.env.local` carries `GEMINI_API_KEY`, and
   `MONTHLY_LLM_BUDGET_USD` / `MAX_EXTRACTION_ATTEMPTS_PER_DAY` are set (unset ⇒
   fail-closed, no paid calls). Claude never writes `.env*`.
2. Bring up the real stack:
   ```bash
   CHEFCLAW_EXTRACTOR=gemini CHEFCLAW_SOURCES=real \
     docker compose up -d --build          # api on 127.0.0.1:8000
   ```
   Rednote rows also need `XHS_SIDECAR_URL` (the internal sidecar) set.
3. Paste each case's URL through the UI (or `POST /api/recipes/extract`), watch
   the job to a terminal state in the jobs drawer, and record the result below.
4. **Escalation rows only:** set `GEMINI_MEDIA_RESOLUTION_MAX=high` (base stays
   `low`) to exercise the one-shot escalation; confirm the escalation log line
   and the summed spend row, then unset it.
5. Cost check: `GET /api/spend` after the run confirms the per-model token/¢
   total for the session.

> Every paid row multiplies quota spend. Run the minimum set that proves each
> behavior; a single well-chosen video per row is enough.

## The matrix

**Run 1 — 2026-07-07, Bilibili only** (Rednote rows need the sidecar; deferred).
Driven directly through the real `BilibiliSource` + `GeminiExtractor` +
`validate_extraction` (no DB/worker — those layers are unit-tested), one video at
a time, yt-dlp anonymous 480p, jittered politeness. Videos referenced by
creator/dish (all public 美食作家王刚 / classic tutorials).

| # | Case | Tier | Expected behavior | Observed (Run 1) |
|---|------|------|-------------------|------------------|
| 1 | Single-dish | Paid | 1 recipe; bilingual; verbatim quantities | ✅ 王刚 红烧肉 → 1 recipe, 16 ing, verbatim (`400克`→400 g/mass, `几根`→approx), 13 steps, est 0/2, tags ok. (1st upload hit a transient Gemini processing fail; **succeeded on retry**.) |
| 2 | Multi-dish | Paid | N recipes under one identity; siblings related | ⚠️ Composite `一鱼两吃` (将军过桥) → model returned **1** dish (a sound judgment — it's one named dish). Extreme 12-dish 年夜饭 → download-timeout (see #4). Clean N-distinct-recipe *live* demo not captured; the atomic N-recipe store is unit-tested (`test_worker`). |
| 3 | Heavy text / **escalation** | Paid | v5 envelope; `unreadable`→ one higher-res retry; summed spend | ✅ v5 envelope prompt works live (clean extraction). Escalation **did not fire** (model reported legible) — the firing path is unit-tested. **Surfaced the `prep_state` bug (below); fixed.** |
| 4 | Long video | Paid | Completes under deadline, or fails typed (retryable), never wedges queue | ✅ 13.5-min video (73 MB) completed within deadlines. Extreme 12-dish video **exceeded the download deadline → typed timeout** (retryable), queue not wedged — the designed behavior. |
| 5 | 适量-heavy | Paid | 适量/少许 → `value:null, unit:null, approx`; no fabricated number | ✅ 脆皮蛋饼 → 15 ing, **7 approx (适量)**, 8 valued, 0 fabricated. Hard Rule 7 intact. |
| 6 | Non-cooking | Paid | `[]` → 0 recipes (not an error) | ✅ A game video → model emitted **1 dish with 0 ingredients** → correctly **`validation_failed`** (raw preserved, nothing fabricated). Not the `[]` path, but the same safe outcome; the drawer copy ("may not be a cooking video, nothing saved") fits exactly. |
| 7 | `b23.tv` short link + dedupe | Free | Same canonical id as the full URL | ✅ `b23.tv/BV…` → **identical** `BV…-p1` as the full URL (tracking params stripped) → dedupe holds. (Redirect-following for random short codes is unit-tested.) |
| 8 | Unsupported / deleted | Free | Typed pre-paid failure | ✅ youtube.com + legacy `av…` id → `unsupported_url`. A nonexistent/deleted BV → `download_failed` (unit-tested; a random BV in-run happened to hit a real video). |
| — | Very-long-ingredient | Paid | Large document validates | Partially covered by #5 (15 ing) + 将军过桥 (13 ing). Dedicated 佛跳墙 not run (cost). |
| — | Rednote video / xhslink / image-note (图文) | — | guest fetch / short-link / `image_note_unsupported` fast-fail | Deferred — Bilibili-only run. Image-note fast-fail is unit-tested (`test_sources`, `test_worker`); live confirm needs the sidecar. |

### Findings & fixes (Run 1)

1. **`prep_state` misuse → whole recipe lost (fixed, two layers).** The model
   sometimes puts knife-work (`"sliced"`, `"cut into chunks"`) in `prep_state`,
   whose enum is only physical states (dried/fresh/cooked/raw/frozen) →
   `validation_failed` rejected the *entire* recipe. **Fix:** (a) tightened the
   `prep_state` guidance in the v4 + v5 prompts (state-only; knife-work belongs
   in `notes`); and (b) a targeted validator canonicalization
   (`_relocate_unknown_prep_state`) that **moves** an out-of-enum value into
   `notes` — where the schema already puts knife-work — and nulls `prep_state`,
   so a residual slip never loses a recipe. This is confined to a descriptor
   field: `prep_state` is not verbatim food-quantity data, so relocating it (the
   model's own value, into the schema-intended field) fabricates nothing — Hard
   Rule 7 (quantities/weights/times/counts) is untouched, and the strict
   reject-whole posture is kept for everything that IS food data.
2. **Gemini Files API "failed to be processed" is flaky.** A transient
   upload-processing failure that is correctly typed `extraction_failed`
   (retryable) — the worker retries up to 3×. Observed it clear on retry, and
   also observed a video fail all 3 attempts, so a video can occasionally be
   un-processable in a burst. No code change: the taxonomy + worker retry + the
   drawer copy ("usually transient — retry to try again") already cover it.
3. **Faithful capture confirmed** across three real videos: verbatim quantities,
   `适量`→approx, genuinely-unstated→`quantity:null`, bilingual names, derived
   estimates + tags — no fabrication anywhere.

### Resolved: descriptor leniency (Braeden, 2026-07-07)

The open question — keep strict vs. add targeted leniency for `prep_state` — was
resolved in favor of **targeted leniency**: descriptor fields get looser, food
data stays strict. `_relocate_unknown_prep_state` (finding 1b) makes it so a
recipe is never lost over a mis-slotted descriptor, while every quantity/weight/
time/count keeps the strict reject-whole, never-coerce posture. The global
Gemini `responseSchema` (constrained decoding) was **rejected** — it would apply
uniform coercion to the food-data fields too and can degrade transcription
fidelity; the two-layer prompt + descriptor-canonicalization fix is preferred.

## Per-case notes

**#3 escalation.** Escalation is **opt-in** (`GEMINI_MEDIA_RESOLUTION_MAX` empty =
off). Off, the pipeline uses the v4 prompt and one call at the base resolution
(today's behavior). On, the Gemini adapter uses the v5 envelope prompt and, when
`capture_quality.on_screen_text == "unreadable"`, retries the same uploaded video
once at the ceiling. Watch the api logs for
`gemini media-resolution escalation: on-screen text unreadable at low — retrying once at high`.
The extraction meta records a `media resolution escalated low → high` warning and
`GET /api/spend` shows one summed row (not two).

**#6 typed-error UX.** The failure taxonomy → jobs-drawer copy map lives in
`frontend/src/components/jobs-drawer.tsx` (`ERROR_GUIDANCE`). Every `error_type`
now renders a specific, actionable line; unknown/future types fall back to a
generic "check the server logs" line. No bare "Error"/"Try again" anywhere.

**#11 image notes.** Handled per ADR option (a): a graceful fast-fail with no
paid call, detected from the sidecar's `作品类型`. A real multi-image→vision path
(option b) is deferred to a future ADR.

## Results log

Record each real run here (date, URL kind, job outcome, spend, bugs found +
fixed). Keep URLs generic — this repo is public; never paste a personal link or
any `xsec_token`.

- **Run 1 — 2026-07-07 (Bilibili, ~8 real videos, well under $0.50 of Gemini
  quota).** Single-dish, 适量-heavy, composite multi-dish, non-cooking,
  long-video-timeout, short-link dedupe, and unsupported-URL cases exercised
  against real Gemini. One bug found + fixed (`prep_state` prompt tightening);
  Gemini Files-API processing flakiness documented (handled by the existing
  retry path). Rednote rows deferred (need the sidecar). N-distinct-recipe and
  live escalation-firing not captured — both unit-tested.
