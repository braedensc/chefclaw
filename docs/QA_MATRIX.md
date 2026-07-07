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

| # | Case | Tier | Exercises | Expected behavior | Observed |
|---|------|------|-----------|-------------------|----------|
| 1 | Single-dish cooking video | Paid | The happy path | 1 job → `stored`; 1 recipe; bilingual doc, verbatim quantities; 1 spend row | ⏳ pending paid run |
| 2 | Multi-dish video | Paid | N-recipe atomic store + sibling display | 1 job → `stored`; N recipes under one `(platform, canonical_id)`; siblings shown as related on the detail page | ⏳ pending paid run |
| 3 | Heavy on-screen text | Paid | Media-resolution escalation | With `GEMINI_MEDIA_RESOLUTION_MAX=high`: model reports `unreadable` at `low` → one retry at `high`; escalation log line; a single **summed** spend row; richer ingredient capture | ⏳ pending paid run |
| 4 | Long video | Paid | Per-stage timeout | Completes under the 900s extract deadline, or fails typed `extraction_failed` ("extraction timed out"), retryable, requeued — never wedges the serial queue | ⏳ pending paid run |
| 5 | 适量-heavy recipe | Paid | Null-quantity faithful capture | Recipe stores; 适量/少许 ingredients keep `raw_text`, `value: null`, `unit: null`, `unit_type: "approx"` — never a fabricated number (Hard Rule 7) | ⏳ pending paid run |
| 6 | Deleted / expired URL | Free | Typed error UX | Rednote: `cookies_expired` (login-required) or `download_failed` (stale `xsec_token`) → drawer shows actionable copy, no Retry burn on deterministic failures; Bilibili: `download_failed`, retryable | ⏳ pending run |
| 7 | Non-cooking video | Paid | Empty-array handling | Model returns `[]` (or `{"dishes": []}`); job → `stored` with **0 recipes**; NOT an error, NOT an escalation trigger | ⏳ pending paid run |
| 8 | Very-long-ingredient recipe | Paid | Large document validation | Stores fully; all ingredients captured; document validates; detail page + card render without layout breakage | ⏳ pending paid run |
| 9a | Bilibili video | Paid | Bilibili source (yt-dlp, DASH+ffmpeg) | Resolves `BVxxx-pN`; downloads 480p; extracts and stores | ⏳ pending paid run |
| 9b | Rednote video | Paid | Rednote sidecar (guest tier) | Resolves 24-hex note id; guest fetch; extracts and stores | ⏳ pending paid run |
| 10a | `b23.tv` short link | Free | Bilibili short-link resolution | Redirect followed → canonical `BVxxx-pN`; dedupes to the same identity as the full URL | ⏳ pending run |
| 10b | `xhslink.com` short link | Free | Rednote short-link resolution | Redirect followed → 24-hex note id, `xsec_token` preserved in `fetch_url` only | ⏳ pending run |
| 11 | Image-note (图文) post | Free | Image-note fast-fail | `作品类型 = 图文` detected after the free metadata call → typed `image_note_unsupported`, **no media download, no paid call**; drawer: "image gallery … paste a video post" | ✅ covered by tests (unit); ⏳ confirm live |

## Per-case notes

**#3 escalation.** Escalation is **opt-in** (`GEMINI_MEDIA_RESOLUTION_MAX` empty =
off). Off, the pipeline uses the v3 prompt and one call at the base resolution
(today's behavior). On, the Gemini adapter uses the v4 envelope prompt and, when
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

_(pending the flagged paid run — filled in after go-ahead)_
