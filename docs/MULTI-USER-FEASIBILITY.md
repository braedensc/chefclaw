# Multi-User Feasibility & Legality Audit — Selling or Sharing chefclaw

**Date:** 2026-07-06 · **Status:** assessment only — no decision taken; multi-user
remains out of scope (V2-D) until a dedicated ADR says otherwise.
**This is research support for a decision, not legal advice.** Any launch
decision that involves hosting for third parties should get one session with a
lawyer first; this document exists so that conversation is short and cheap.

**Question audited:** what would it take — legally and technically — to turn
chefclaw from a personal single-user app into something sold, or shared
publicly for free, as a hosted service? Method: two code inventories of this
repo plus six web-research passes (platform ToS & Chinese enforcement law; US
copyright/DMCA/§1201; commercial comparables & Gemini terms; operating
entity/data law; free-vs-paid deltas; AGPL monetization mechanics), July 2026.
Claims below are sourced; where a conclusion is analysis rather than a sourced
fact it is marked *(inference)*.

---

## TL;DR

Legality is the gate, not infrastructure — and it forks on **one architectural
question: who fetches the content.**

| Path | Shape | Legal posture | Verdict |
|---|---|---|---|
| **A. Self-host only** (status quo) | AGPL repo; each user runs their own instance, own keys, own platform posture | The code is already shared publicly for free. Publishing extraction-framed code has no meaningful new exposure (the yt-dlp lesson); operator-acts liability sits with each self-hoster, whose personal use is the lowest-risk category | **Already live. Zero new legal surface.** |
| **B. Hosted product, user-supplied uploads only** | Users upload videos they saved themselves; the hosted service never touches Bilibili/Rednote | Moves chefclaw from the scraper category into the mature Otter/Dropbox "process what the user gives us" category: DMCA 512(c) actually fits, no operator-side ToS breach, volition sits with the user | **The cheapest safe hosted path.** Tier-2 `LocalFileSource` + the upload UI are the existing foundation |
| **C. Hosted link-paste service** (current UX, multi-user) | The service fetches from the platforms for third parties | Commercially validated (ReciMe, Samsung Food, Mela do exactly this, unenforced for years) but every fetch is a ToS breach by the *operator*, the Chinese unfair-competition case law fits this exact fact pattern, and payment processors can freeze first and ask questions never | **No-go without a counsel session** and the mitigations in §1.6 |

**Recommendation** *(inference — the decision is the owner's)*: stay on A
today; if productizing is ever wanted, build toward **B** — it keeps the
product (extraction, bilingual library, nutrition/planning intelligence
later) while removing the operator-side platform conduct entirely. C should
not be attempted casually: free-vs-paid barely matters legally; the step
change is hosting platform fetches for third parties *at all*.

Charging money changes less than expected on the copyright/ToS side (the
breach already exists at $0) but adds two hard new surfaces: subscription
consumer-protection law (ROSCA, state auto-renewal statutes) and payment
processors, whose "facilitates copyright infringement" and
"cyberlocker/file-sharing" clauses are enforced by account freeze, no court
required.

---

## 1. Legality

### 1.1 Platform ToS and Chinese-law exposure

**The prohibition doesn't change across tiers — it already exists today.**
Bilibili's User Service agreement (§4.3.15) bans obtaining platform content
"in any way" by "automatic programs, scripts... spiders, crawlers" without
written permission, with no personal-use carve-out; Xiaohongshu's agreement
prohibits scraping/"simulated downloads" and third-party tooling, and XHS
backs it with an active technical arms race (rotating `x-s`/`x-t` request
signing, cookie gating, fingerprinting, dynamic watermarks). What changes at
multi-user is **detectability** (aggregated traffic through one service is
what platform risk-control is built to catch) and **which body of law starts
to fit**:

- **Civil (China, Anti-Unfair Competition Law):** the decided cases — Weibo v.
  Maimai (¥2M+, Beijing IP Court 2016), Dianping v. Baidu (¥3.23M, Shanghai
  2016), XHS v. "Gujiao Video Assistant" (¥150k) — all turned on **using
  scraped data to serve a product to third parties**. That is precisely the
  shape of a public chefclaw and precisely not the shape of personal use.
  Notably, in the Gujiao case, bulk downloading *with watermarks intact* was
  held not unlawful — the liability attached to defeating
  watermark/attribution protections. chefclaw's pipeline preserves source
  attribution as provenance, which matters *(inference)*.
- **Criminal (China, Criminal Law Art. 285 — illegally obtaining computer
  system data):** the one on-point prosecution (an XHS scraping operation)
  required four elements together: front-end verification bypass at scale,
  real revenue (¥6.53M confiscated), PRC domicile, and a distinct privacy
  harm (mass unsolicited DMs). A US paid service would reproduce at most two
  (bypass + revenue) and lacks any PRC nexus; no precedent was found of a
  Chinese platform pursuing a foreign solo operator to judgment, civil or
  criminal.
- **Extraterritorial reality:** the mechanisms actually available against a
  US operator are technical countermeasures (near-certain at scale),
  DMCA/GitHub or hosting takedowns, and app-store complaints — not
  courtrooms. The empirical signal cuts both ways: XHS-Downloader and
  MediaCrawler remain untouched on GitHub after years of visibility, but a
  branded commercial service is a single throat to choke in a way an
  open-source repo is not *(inference)*.
- **The hiQ caution (US):** hiQ Labs won the CFAA question against LinkedIn
  and still ended under a $500k breach-of-contract judgment, because an
  account/ToS relationship existed. Any account-tier XHS access at product
  scale recreates that hook. The existing tiered-access policy (guest-only
  default, main account never) is already the right posture; a hosted
  product would have to be **guest-tier-only, ever** — and even that stays a
  ToS breach on the fetch itself.

One verification note for the record: whether the Bilibili adapter hits
`bilibili.com` (mainland agreement, PRC governing law) or `bilibili.tv`
(overseas entity) affects which contract nominally applies; the research
could not confirm the overseas agreement's terms. Worth a one-line factual
check if C is ever seriously considered.

### 1.2 US copyright — where the line actually runs

The doctrine separates chefclaw's two artifacts cleanly:

**The recipe document is the safe part.** Ingredient lists are unprotectable
facts and directions are an unprotectable "process" under 17 U.S.C. §102(b) —
Publications Int'l v. Meredith (7th Cir. 1996), Tomaydo-Tomahhdo v. Vozary
(6th Cir. 2015), Copyright Office Circular 33. A faithful English rendering
of functional instructions ("加两大勺生抽" → "add two tablespoons of soy
sauce") re-expresses unprotected process, not protected expression, so the
translation is not a meaningful derivative-work problem *(inference, strong)*.
The danger zones inside the output are narrow: verbatim transcription of a
creator's expressive narration/storytelling (Barbour v. Head), wholesale
copying of a creator's written caption, and embedded frames. Rule of thumb:
**translate the recipe, not the performance** — which is what the extractor
schema already does.

**The video is the dangerous part.** Downloading is reproduction; serving
retained copies, frames, or streams to *other* users adds distribution,
public display, and public performance — each separately actionable:

- *Transient fetch → extract → discard* is well-positioned under the
  intermediate-copying fair-use line (Sega v. Accolade; Authors Guild v.
  Google; Bartz v. Anthropic (N.D. Cal. 2025): training use "exceedingly
  transformative", and acquisition-from-source beats the pirated-library
  facts that failed there). Extracting *unprotectable* facts is a stronger
  posture than Thomson Reuters v. Ross (fair use rejected where the output
  competed in the source's own market — a recipe card does not compete with
  watching a cooking video) *(inference)*.
- *A retained archive served to users* is the losing posture: Fox News v.
  TVEyes (archive + re-serve clips: fair use rejected), Disney v. VidAngel,
  ABC v. Aereo. Bartz also held **retention as a permanent library** fails
  fair use independently of the transformative use. The plan's own note
  (media retention is a personal-use feature; flips to `discard` at
  multi-user) is exactly right, and this audit hardens it into a design
  invariant: **the retained low-res copy is operator-private pipeline
  scratch, never rendered to other accounts; recipe cards for other users
  carry the source link, never the source video.** Poster-frame thumbnails
  served cross-user are public display; if ever needed, Perfect 10-style
  link-out thumbnails are the only defensible form.
- **Damages reality:** Chinese works are US-protected without registration
  (Berne), but 17 U.S.C. §412 bars statutory damages and attorney's fees for
  infringement commencing before US registration — which almost no
  Bilibili/XHS creator will have. Practical exposure per work is actual
  damages on a short cooking video: small, fee-shifting unavailable, suit
  probability low. The tail risks: a creator/MCN registering a batch and
  pointing at *newly ingested* videos (fresh infringement post-registration
  → full statutory range, $750–$30k/work, $150k willful), and §1201.
- **§1201 anticircumvention is the sleeper.** It needs no infringement and no
  registration, has its own statutory damages ($200–$2,500 per act), and its
  *trafficking* prong reaches **published code** — that was the RIAA's actual
  theory against youtube-dl in 2020 (reversed by GitHub after EFF's
  rebuttal, never litigated). Ticketmaster v. RMG held a CAPTCHA to be a
  technological protection measure; XHS's request signing sits between that
  case and the EFF's "computing the expected signature is using the system
  as intended" position — genuinely unsettled. chefclaw's repo orchestrates
  yt-dlp/XHS-Downloader rather than shipping bypass logic of its own, and
  its framing is extraction-centric; keep both true. Never ship first-party
  sign-bypass code; never market "download videos from Bilibili/XHS."

**Liability allocation:** the hosted-service **operator** carries the highest
exposure (all acts run on their servers; §512 fit is poor — below). The
**repo publisher** carries low-moderate exposure dominated by §1201 framing
(Sony/Betamax shields tools with substantial non-infringing uses; Grokster
inducement turns on marketing). **Self-hosting users** are the lowest-risk
category (private, non-redistributed, Sony time-shifting-adjacent). Two
sobering notes for the operator row: an **LLC does not shield** a solo
founder from IP infringement they personally direct — the personal
participation doctrine, and Asher Worldwide (individuals who "comprise the
entire workforce" *are* the corporation) is the one-person-company fact
pattern exactly. And AGPL licenses only the software's own copyright; it says
nothing about the legality of what the software fetches. An LLC is still
worth having for a real product (contracts, banking, non-personally-directed
risks), but the actual levers on the core exposure are architecture and
insurance, not entity form *(inference)*.

### 1.3 DMCA §512 — poor fit for fetching, proper fit for uploads

For a link-paste service (path C), none of the four safe harbors fits well:
the service is not a conduit or cache, and §512(c) covers "storage at the
direction of a user" — but the user supplies a *URL*, and the **service's own
code performs the reproduction**. The volitional-conduct doctrine (Cartoon
Network v. Cablevision) genuinely helps the per-user fetch-and-extract step,
and collapses for anything retained and re-served (Aereo, Zediva, VidAngel)
*(inference)*. For a user-upload service (path B), §512(c) is squarely the
designed-for shape — it is what Dropbox/YouTube rely on.

Either hosted path should register a DMCA agent anyway (verified primary:
**$6 per designation, online-only, expires after 3 years**; renewal = re-pay
$6), adopt a repeat-infringer policy (§512(i) requires it and the ToS
termination clause is its mechanism), and run honest notice-and-takedown.
For B it is real armor; for C it is good-faith mitigation only.

### 1.4 Free vs. paid — what actually changes

- **Platform ToS:** nothing new — the automated-access ban is unconditional
  and already breached at $0. Charging adds a second, stacked violation
  (commercial-use clauses) and raises enforcement priority, but the
  personal→service step matters far more than the free→paid step.
- **Copyright fair use:** commerciality is one factor, not dispositive
  (Campbell; Google Books won while commercial). What kills fair use is
  same-purpose substitution at scale (Warhol; Ross) — scale, not the price
  tag, is the variable that moves factor four *(inference)*.
- **New at paid, cleanly:** ROSCA (federal) and state auto-renewal laws
  (California ARL as the de facto baseline: express consent, clear
  disclosure, same-medium cancellation) with real per-violation penalties;
  and **payment processors** — Stripe prohibits "cyberlocker and file-sharing
  services" and anything that "facilitates infringement," and restricts
  third-party-content platforms behind preapproval. A retained-video archive
  served to users reads as a cyberlocker; a structured-recipe-data service
  does not *(inference)*. Processor freezes move faster than any lawsuit and
  need no legal finding.
- **Free-share is not a legal free pass:** the AUCL cases and the copyright
  analysis attach to serving third parties, not to revenue. Free hosting of
  path C still crosses the redistribution line; it just removes the
  consumer-protection/processor surfaces and the "illicit gains" aggravator.

### 1.5 Operating scaffolding (any hosted path)

- **Entity:** single-member LLC ≈ $35–$500 to form, $0–$800/yr to keep
  (state-dependent). Worth it for a real product; not a shield for the core
  IP risk (§1.2). Media/tech E&O insurance is the complementary lever — get
  quotes before launch *(inference)*.
- **ToS:** the Otter.ai pattern is the template — user warrants they own or
  are licensed to use whatever they upload/link, indemnifies the operator
  for IP claims arising from it, grants a processing license; plus
  termination/repeat-infringer, as-is warranty disclaimer, limitation of
  liability, governing law. Google's Gemini terms do **not** shift input-IP
  responsibility onto Google — the operator's own ToS is the only place that
  risk gets allocated to the person who chose the content.
- **Privacy policy:** disclose the data actually collected and **name Google
  Gemini** as the processor (cheap, closes the FTC deception-by-omission
  angle). **Gemini paid tier is mandatory operating policy at multi-user**:
  the free tier is training-eligible and human-reviewed — indefensible for
  other people's uploads — and the paid tier comes with Google's Cloud Data
  Processing Addendum. CCPA does not apply below its thresholds ($26.6M
  revenue / 100k CA consumers); honor access/deletion requests anyway —
  the hard-delete + `owner_id` partitioning already make both trivial.
- **GDPR:** a US-only posture keeps it out of scope — under the EDPB
  targeting test, mere accessibility from the EU is not "offering services"
  to EU data subjects; no EU languages/currency/marketing (an affirmative
  geo-limit is the belt-and-suspenders version). If the EU is ever targeted:
  lawful bases, Art. 28 processor terms (Google's DPA exists, self-serve),
  data-subject rights within 30 days; no DPO at this scale.
- **PIPL:** its extraterritorial trigger is offering services to people *in*
  China or analyzing their behavior; a US-facing recipe app plausibly trips
  neither. Creator names/handles inside extracted documents are personal
  information of persons in China, but processing them incidentally for a
  US user base is a marginal-fit fact pattern, and the practical enforcement
  lever against a no-China-presence operator is market access, not
  collectible fines *(inference — thinnest-sourced area of this audit; note
  a Guangzhou Internet Court judgment has applied PIPL extraterritorially
  where a foreign company served customers in China)*.
- **AGPL monetization (already decided in the licensing ADR, confirmed):**
  the FSF's own FAQ states the copyright holder is not bound by their own
  license and may license under different terms at will — dual licensing is
  standard practice (Mattermost states the "copyright holder... exclusive
  right" mechanism explicitly; Nextcloud monetizes hosting/support on a
  single AGPL codebase with no dual license at all, the closest structural
  analog to chefclaw). One preserved-optionality rule: **outside
  contributions accepted without a CLA are AGPL-only and would freeze
  dual-licensing** — if the repo ever takes non-trivial external PRs, add a
  CLA/DCO-with-license-grant first. Hosting chefclaw as a service creates no
  AGPL conflict for its sole author; §13 obligations (offer Corresponding
  Source to network users of a modified version) bind other operators, and
  self-imposing them costs nothing since the repo is public anyway.
- **Hosted UGC housekeeping** (path B): user uploads create standard provider
  duties — abuse reporting channels and NCMEC reporting on actual knowledge
  of CSAM (18 U.S.C. §2258A), plus an acceptable-use policy. Boring,
  necessary, cheap.

### 1.6 The de-risking pivot: user-supplied content only (path B)

**Verdict: yes — it sidesteps the operator-side ToS problem while keeping the
product** *(inference, and the audit's central finding)*.

What it is: the hosted product accepts only file uploads (the tier-2
`LocalFileSource` path — content-addressed, already wired end-to-end, with
the upload UI shipped). The hosted build performs **zero platform fetches**:
paste-a-link either disappears from the hosted product or degrades to
"here's how to save the video on your phone, then upload it." Self-hosters
keep the full adapter set — their instance, their conduct, their posture.

What it fixes: no automated access to Bilibili/XHS by the operator (no ToS
breach, no AUCL "obtaining" conduct, no cookie/account hook, no arms-race
exposure); §512(c) fits as designed; volition sits with the user
(Cablevision posture at its strongest); Stripe categorization is a
data-processing SaaS, not a downloader; the acquisition step happens on the
user's own device, where personal-use is the lowest-risk category.

What it does not fix: the uploaded video is still someone's copyrighted work
— the operator holds it (per-uploader-private, never cross-served) and
processes it, allocating IP responsibility to the uploader via the Otter
pattern ToS (§1.5); the mature precedent is that this category
(Otter/Rev/Dropbox/Evernote) has operated for decades essentially
unlitigated, with enforcement being per-file takedowns, not platform suits.
The public repo's §1201/framing considerations are unchanged (and already
handled).

Product cost: convenience. Two taps (share-sheet → upload) instead of one
paste. The V2-C mobile-upload work (share sheet, camera roll, PWA) is
exactly the mitigation, and it's already on the roadmap. Notably, the
commercial comparables are converging on adjacent shapes — Samsung Food
built a creator-consent import channel ("Jumps") after friction with raw
TikTok video *(observed; mechanism partially inferred)*.

**Free-tier abuse note:** uploads cost real Gemini money per extraction, so a
free public tier is an abuse magnet. The per-owner budget/caps plumbing that
already exists (§2.4) is the metering foundation; comparables validate
metered free tiers (ReciMe: 5 imports/week free, ~$60/yr unlimited).

---

## 2. Feasibility — what must change to go multi-user

The data model kept its promise: `owner_id` is on every user-owned row from
migration #1, every CRUD query filters by it, and auth is genuinely one
swappable dependency. The gaps are real but enumerable.

### 2.1 Inventory

| Area | State | Evidence | Verdict |
|---|---|---|---|
| Auth dependency | `require_owner` validates one bearer token, resolves the single seeded owner, returns `uuid.UUID`; every router depends on it | `backend/src/chefclaw/auth.py:38-85` | **READY as a seam** — swap the internals, keep the contract |
| CRUD tenancy | recipes/jobs/spend reads & writes all owner-scoped | `services/recipes.py:37,59`, `services/repo.py:199-213`, `spend.py:139-154` | **READY** |
| Spend ledger & budget gate | ledger rows and both cap checks are per-`owner_id`; caps themselves are two global env vars | `spend.py:139-183`, `config.py:35-36` | **PARTIAL** — enforcement is per-owner already; per-user *limits* need `users` columns + admin surface |
| Dedupe | `find_active_job`, `find_completed_job_with_recipes`, `find_recipe_ids` match `(platform, canonical_id)` with **no owner filter**; `UNIQUE(platform, canonical_id, dish_index)` has no `owner_id` | `services/repo.py:137-174,249-256` | **MISSING for multi-user** — cross-tenant metadata leak (user B pasting user A's URL attaches to A's job and sees A's recipe ids), and a legal fork: global dedupe = one stored copy served to many users (redistribution-shaped); per-owner dedupe = each copy user-directed *(inference)*. Path B sidesteps most of it (content-addressed per-upload), but the constraint still needs `owner_id` |
| Job worker | strictly-serial in-process worker; double-spend race closed only at concurrency 1; single-uvicorn-worker rule is documented, not enforced; startup reconcile flips ALL running jobs | `services/jobs.py:214-287`, `services/repo.py:53-68`, jobs ADR | **MISSING for scale** — see §2.3 |
| Rate limiting / upload cap | none anywhere; upload endpoint streams unbounded | `routers/extraction.py:31,91` | **MISSING** (was already a V2-D residual) |
| Media | retention knob global; retained files on the named volume keyed by platform/canonical_id (not owner); **no media-serving endpoint exists yet** | `config.py:37,76`, `services/jobs.py:572-604` | **PARTIAL** — nothing is served today, so nothing leaks today; the V2-E poster-frame feature must land owner-scoped, and multi-user flips retention to `discard` (per plan §16.12) |
| Frontend auth | token in localStorage via one seam (`token.ts`, `api.ts`), 401 recovery exists | `frontend/src/token.ts`, `api.ts:12-15` | **READY as a seam** — needs a login page instead of a token gate |

### 2.2 Auth (hard blocker, path B or C)

Replace the internals of `require_owner` with real per-request identity:
signup/login (sessions or OAuth or passkeys — pick one, the service layer
doesn't care), password/passkey storage, email verification, token/session
rotation, and a per-user API-token story for programmatic clients. The
`users` table needs the columns identity brings (email, credential hash,
status) plus per-user caps (§2.4). Frontend: login/signup pages replace the
token gate. Effort: **M (1–2 weeks)** — the seam is honest, nothing in the
service layer changes.

### 2.3 Jobs: the graduation path (hard blocker for real concurrency)

The no-broker design is load-bearing and correct at one user: the jobs ADR
names **TaskIQ** as the exit, and the worker already talks only through the
`JobStore` protocol (`services/repo.py:71-126`), so the transport swaps under
it without touching business logic. What real multi-user forces on top:

- **Broker + multiple workers** (TaskIQ) so concurrent extractions don't all
  serialize behind one in-process queue.
- **Move the idempotent paid-call gate** out of the worker's "re-check
  recipes before extracting" (safe *only* at concurrency 1) and into the
  claim transaction or a per-canonical-id lock — otherwise the double-spend
  race the whole design exists to close reopens the moment a second worker
  runs. This is the correctness-critical piece.
- **Per-owner fairness:** one user's 50-video batch must not starve everyone
  else — TaskIQ priorities or per-owner queues.
- **Scope the startup reconcile:** today it flips *all* running jobs to
  `interrupted` at boot (`services/repo.py:320-337`); with sibling workers
  that would kill jobs another worker is mid-flight on. It must only reclaim
  the booting worker's own jobs.

Effort: **L (2–4 weeks)** and the riskiest technical work in the list — the
double-spend gate is where a bug costs real money. Note **path B changes the
arithmetic**: user uploads are content-addressed per upload, so cross-user
dedupe (and its race) largely disappears, and concurrency becomes a
throughput want rather than a correctness gate. B is cheaper here too.

### 2.4 Per-user cost & abuse control

The *enforcement* plumbing is already per-owner — the ledger and both cap
checks filter on `owner_id` (`spend.py:139-183`). What's missing is per-user
*policy* and the abuse controls a public endpoint needs:

- **Per-user caps:** `monthly_budget_usd` + `max_attempts_per_day` columns on
  `users`, joined into `check_budget` in place of the two global env vars
  (`config.py:35-36`).
- **Gemini paid tier** — not merely the privacy requirement it is today (free
  tier is public-videos-only and training-eligible): paid is required to
  process arbitrary user uploads at all. Wire real pricing into `spend.py`'s
  `GEMINI_PRICING` (currently conservative estimates).
- **Request rate limiting** — none exists on any route today; add per-token /
  per-IP throttling on `extract` and `upload`.
- **Upload size cap** — the upload endpoint streams unbounded
  (`routers/extraction.py:31,91`), so any authed client can fill the disk; add
  a hard `MAX_UPLOAD_BYTES` check before reading.
- **Abuse enforcement:** lock a user whose spend or failure rate spikes; the
  per-owner 80/100% budget alert already shipped (V2-A) is the foundation.

Effort: **M (1–2 weeks)**. Comparables validate a metered free tier (ReciMe:
5 imports/week free, ~$60/yr unlimited) — the shape to copy.

### 2.5 Storage

Today: retained videos on a named Docker volume keyed by
`platform/canonical_id` (no owner in the path), and **no media-serving
endpoint exists** — so nothing leaks today because nothing is served. Multi-
user forces:

- **`MEDIA_RETENTION` flips to `discard`** (or a paid storage tier) per plan
  §16.12 — hosting copies of platform content for others *is* the
  redistribution line. Keep only what is per-uploader-private and actually
  needed, never cross-served.
- **Object storage** (S3 / R2 / B2) instead of a local volume once there is
  more than one box; owner-scoped keys and signed, owner-checked URLs for any
  serving. The V2-E poster-frame feature must land owner-scoped from the
  first commit, not retrofitted.
- **Backups get smaller, not bigger:** extracted JSON is kilobytes per user,
  so multi-user backups are ordinary tiny DB dumps — the irreplaceable-media
  backup obligation is a personal-use artifact (plan §16.12).

Effort: **S–M**, mostly config plus an object-store adapter behind the
existing media seam.

### 2.6 Multi-tenant isolation testing & security hardening

Multi-user turns owner-scoping from a nicety into a **security boundary**,
which has to be tested as one:

- **An isolation test suite:** for every route, prove user B cannot read,
  mutate, or delete user A's recipes, jobs, spend, or media. The dedupe leak
  in §2.1 is exactly the class of gap these tests exist to catch.
- **Close the cross-tenant dedupe leak** (add `owner_id` to the three
  unscoped queries + the `UNIQUE` constraint) — a migration plus code; worth
  doing to harden the seam even before launch.
- **The V2-D residuals become mandatory, not optional:** rate limiting,
  upload cap, prompt-injection hardening on user-supplied titles/metadata fed
  to Gemini (frame user data as data, not instructions), and a token/session
  rotation story.
- **Treat SPA/static serving and any media endpoint as authenticated
  boundaries**, not incidental routes.

Effort: **M**, and it gates any launch.

### 2.7 Infra

The single-uvicorn, compose-on-one-box shape is right for single-user and
wrong for multi-user. The scalable shape:

- **Managed Postgres** (RDS / Cloud SQL / Neon) instead of the Docker volume.
- **Object storage** (§2.5).
- **And only here does serverless finally fit.** With an external broker, a
  managed DB, and an object store, the stateless API can run on Cloud Run /
  Fly Machines / autoscaling containers — which it explicitly does *not* for
  the single-user compose stack, whose entire design is one box, one worker,
  local volumes (that's why Cloud Run was ruled out for the MVP). The job
  worker stays a separate long-running consumer, not a serverless function.
- **Access model inverts:** Tailscale-gated private access no longer applies;
  a public product needs real edge TLS (managed / Caddy), a WAF or rate-limit
  layer, and the §2.6 hardening.

Recurring cost sketch *(inference, small scale)*: managed Postgres
~$15–30/mo, object storage a few $/mo, container hosting ~$10–40/mo, plus
Gemini paid per extraction (~$0.02–0.25/video, metered and passed through) —
order of magnitude **low tens of dollars/month baseline**, dominated by
per-extraction LLM cost at volume. Versus ~$0–5/mo for the current
Tailscale-gated single-user VPS.

---

## 3. Prioritized change-list & go/no-go

Legal/product-shape gates first — they decide whether any technical work is
worth starting — then the technical work in dependency order.

### Legal & product-shape gates (cheap, decisive, do first)

- **L1 — Decide the fetch model: path B (user-upload only) vs C (link-paste).**
  This is *the* decision; everything else follows from it. Recommendation: B.
- **L2 — One counsel session before any hosted launch:** fair-use posture of
  the pipeline, ToS/indemnity language, payment-processor risk. Cheap and
  short precisely because this document scopes it.
- **L3 — If B, make the hosted build fetch nothing:** paste-a-link disappears
  from the hosted product or degrades to "save it on your phone, then upload";
  self-hosters keep the full adapter set (their instance, their conduct).
- **L4 — Design invariant, either path:** retained media is
  operator/uploader-private, never cross-served; cards carry the source
  *link*, not the source *video*.
- **L5 — Paperwork:** LLC (optional, cheap, and not a shield for the core IP
  risk); Otter-pattern ToS (uploader warranty + indemnity + processing
  license); privacy policy naming Gemini; DMCA agent ($6); repeat-infringer
  policy; US-only geo-posture; Gemini paid tier.
- **L6 — Preserve AGPL optionality:** add a CLA / DCO-with-license-grant
  *before* the first non-trivial outside PR, or dual-licensing freezes.

### Technical (only if a hosted path is chosen)

- **T1 — Auth:** real identity behind `require_owner` + login/signup UI. **M.**
  *(hard blocker)*
- **T2 — Close the cross-tenant dedupe leak:** `owner_id` on the three
  queries + the `UNIQUE` constraint. **S**, and a genuine security fix.
  *(correctness blocker)*
- **T3 — Per-user caps + rate limiting + upload cap + Gemini paid pricing.**
  **M.** *(abuse/cost blocker)*
- **T4 — Jobs:** TaskIQ + multiple workers + move the double-spend gate into
  the claim + per-owner fairness + scoped reconcile. **L**, riskiest.
  *(concurrency blocker; materially cheaper under B)*
- **T5 — Storage:** object store behind the media seam, owner-scoped serving,
  retention → `discard`. **S–M.**
- **T6 — Multi-tenant isolation test suite + V2-D hardening.** **M**, gates
  launch.
- **T7 — Infra:** managed Postgres + object storage + autoscaling containers +
  edge TLS. **M.**

### Go / no-go

- **Path A (self-host, status quo): GO** — already live, zero new legal
  surface, nothing to build.
- **Path B (user-upload hosted): GO-ABLE** — the only hosted path that is
  legally clean. Roughly **2–3 months** of focused work (T1–T7, T4 cheaper
  under B), **low-tens-of-dollars/month** infra, one counsel session. The
  product stays intact; the only loss is paste-a-link convenience, which the
  already-roadmapped V2-C mobile-upload work (share sheet, camera roll, PWA)
  offsets.
- **Path C (link-paste hosted): NO-GO** without counsel *and* an explicit
  acceptance of standing operator-side ToS/redistribution exposure,
  payment-processor fragility, and an ongoing arms race with XHS. It is what
  the market leaders (ReciMe, Samsung Food, Mela) actually do, unenforced for
  years — but that is their risk appetite as larger entities with legal teams,
  and B captures ~95% of the product at a fraction of the risk.

### Recommendation *(inference — the decision is the owner's)*

Stay on **A** today. If productizing ever becomes the goal, build **B**, and
treat the **extraction/intelligence layer** — nutrition, meal planning,
fitness, the pillars the plan already scopes — as the monetizable surface,
exactly as §0.1 predicted ("shift the monetizable surface away from scraping;
charge for the intelligence over recipes users add"). The single
highest-leverage prep step that costs almost nothing now: keep the
hosted-vs-self-host fetch boundary clean in the adapter layer so B is a
config split rather than a refactor — and add a CLA before outside
contributions arrive.

---

*Sources: the two code inventories (file:line evidence inline above) plus six
July-2026 web-research passes. Load-bearing primary legal sources include 17
U.S.C. §102(b) / §412 / §512 / §1201; Publications Int'l v. Meredith (7th Cir.
1996); Tomaydo-Tomahhdo v. Vozary (6th Cir. 2015); Fox News v. TVEyes (2d Cir.
2018); Bartz v. Anthropic (N.D. Cal. 2025); Thomson Reuters v. Ross (D. Del.
2025); MGM v. Grokster (2005); hiQ v. LinkedIn (9th Cir. 2022);
Campbell/Warhol; the FSF GPL FAQ and AGPL-3.0 §13; EDPB Guidelines 3/2018;
PIPL Arts. 3/13/27/42; and copyright.gov (DMCA-agent $6 fee). The Chinese
civil/criminal ToS cases (Weibo v. Maimai, Dianping v. Baidu, XHS v. Gujiao,
the Art. 285 XHS prosecution) are sourced to Chinese-language legal reporting.
Not legal advice — see the header caveat.*