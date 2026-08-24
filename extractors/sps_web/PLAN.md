# Plan: every SPS board-approved contract, 2005 → present, with citations

Goal: a spreadsheet (and BigQuery table) with one row per contract action
the Seattle School Board took — new contract, amendment, change order,
renewal, final acceptance — with vendor, amount, dates, department, funding
source, board action/vote, and a **primary-source citation** (document URL +
page) for every row, so vendors can be analyzed longitudinally.

Strategy: (1) download every board agenda, minutes, and Board Action Report
(BAR) we can reach, (2) turn them into text, (3) segment agenda items,
(4) extract contract facts from contract-like items with an LLM under a
strict schema, (5) normalize vendors and link amendments to parents,
(6) QA by sampling back to the PDFs, (7) publish.

This document is written to be executed by subagents. Section 1 is the
verified source map (scouted 2026-08-24 — do not re-scout, just verify
spot-checks). Section 2 is the pipeline design. Section 3 is the task list,
one card per subagent, with a recommended model.

---

## 1. Source map (verified)

There is no single archive. Coverage is stitched from five sources across
three website generations. All fetch mechanics below were tested with `curl`.

| Era (meeting dates) | Source | Listing mechanism | Document fetch | Docs (approx) | Notes |
|---|---|---|---|---|---|
| **Aug 2016 → present** | seattleschools.org WordPress, post type `board_meeting` | `GET https://www.seattleschools.org/wp-json/wp/v2/board_meeting?per_page=100&page=N` — 443 meetings, 5 pages; `X-WP-Total` header; taxonomy `school_year` (ids → names via `/wp-json/wp/v2/school_year?per_page=100`), `board-meetings/meeting-type` | Links inside `content.rendered` | ~4,000 | Robots.txt allows. Two attachment hosts by year (next two rows). |
| ↳ 2016-17 → 2020-21 meetings | same | same | `https://www.seattleschools.org/wp-content/uploads/2021/07/<file>.pdf` (migrated copies), direct GET, all 200 | ~2,175 PDFs | File names carry item codes: `C01_20210707_Minutes_20210609.pdf`, `SC01_…` (consent), `A01_…` (action), `I01_…` (intro). Agenda, minutes, BARs, warrants. |
| ↳ 2021-22 → present | same | same | SharePoint share links `https://seattleschools.sharepoint.com/:b:/s/SPSBoardOffice-O365/<TOKEN>?e=…`. **Do not follow the share link with curl** (bounces to MS login). Fetch `https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365/_layouts/15/download.aspx?share=<TOKEN>` → 200 `application/pdf`, no auth. Resolved path (from `guestaccess.aspx?share=<TOKEN>`) gives the human name: `…/School Board/Board Meetings/2025-26/2025-12-10 Regular/20251119_RBM_Minutes_rev20251205.pdf`. | ~1,830 PDFs | Anonymous guest access; tokens are stable but download everything now. |
| **2011-12 → 2015-16** (and overlapping copies through 2020-21) | Blackboard-era site, `www.seattleschools.org/UserFiles/Servers/Server_543/File/District/Departments/School Board/<YY-YY> agendas/<MMDDYYYYagenda>/…` | Site is gone; enumerate via Wayback CDX: `http://web.archive.org/cdx/search/cdx?url=seattleschools.org/UserFiles/Servers/Server_543/File/District/Departments/School%20Board/*&collapse=urlkey&fl=timestamp,original,statuscode` (use `curl -g`) → 7,139 URLs, 5,829 with a 200 capture | `http://web.archive.org/web/<timestamp>id_/<original>` returns the raw PDF | 11-12: 40 files; 12-13: 172; 13-14: 178; 14-15: 139; 15-16: 520 (incl. 251 action reports); 16-17: 432 | Folder names vary (`15-16agendas`, `15-16%20agendas`, `ADA/` subfolder holding `YYYYMMDD_Agenda.pdf` / `_Minutes.pdf`). Also `Friday Memos/` (1,758), `committees/`, `Policies/`, `Resolutions/` — out of scope except committees if needed. 2011-12 is thin. |
| **2005-06 → 2010-11** | Legacy site `www.seattleschools.org/area/board/<YY-YY>agendas/<MMDDYYagenda>/*.pdf` (2008-09 on) and `/area/board/<MMDDYYagenda>/*.pdf` (2005–2008); minutes in `/area/board/05-06boardminutes/`, `06-07boardminutes/`, `07-08minutes/` | Wayback CDX `url=seattleschools.org/area/board/*` → 1,997 URLs, 1,168 with a 200 capture | Wayback `id_` raw fetch (tested: `20080706153915id_/…/010908agenda/010908agenda.pdf` → PDF) | ~1,100 | Per-meeting folders hold `<MMDDYY>agenda.pdf`, `<MMDDYY>minutes.pdf`, and item attachments incl. `*actionreport.pdf`, `passcontract.pdf` etc. Agenda PDFs are 2-page item lists (titles, mostly no amounts) — the minutes and action reports carry vendor/amount. Pre-2005 `/area/board/` has only resolutions. |
| **2006 → 2012** (supplement) | SPS Archives file server `https://spsarchivepublic.seattleschools.org/PublicDocuments/Board-Documents/Meeting-Minutes/<YYYY-MM-DD>/edited-<MMDDYY>agenda.pdf` indexed by ArchivesSpace (`archivespace.seattleschools.org`, 231 digital objects, search UI 10/page) | Server currently **unreachable** (TCP reset for curl and Chrome). Wayback CDX `url=spsarchivepublic.seattleschools.org/*` → 232 URLs, 223 with 200 captures | Wayback `id_` raw fetch (tested) | 223 | "Edited agendas" per meeting 2006–2012 (10/27/24/26/43/52/47 per year). Use to fill 2011-12 and as a cross-check. |
| pre-2005 | WA State Digital Archives title 551 ("coming soon"), SPS Archives (206-252-0796, archives@seattleschools.org) | none online | manual request | — | Out of scope for automation; note in COVERAGE. |

Where the contract facts live (checked in real PDFs):

- **Minutes (2016+, and legacy `*minutes.pdf`)** — the single best per-meeting source. Modern minutes list every business item with its motion text ("…authorize the Superintendent to approve the contract amendment with Academy for Precision Learning in the amount of $620,000, for a revised total contract amount of $1,595,252…"), the vote, and whether it passed; the warrant report table (vendor payments by fund) is also there.
- **Board Action Reports** — one PDF per item; give contract number/PO, term, department, funding source (BEX/BTA/General), procurement method, and fiscal impact narrative. Essential for detail, but they exist on the item's introduction meeting and are re-linked at action.
- **Agendas** — item titles + "Approval of this item will…" descriptions; amounts only sometimes. Use for segmentation and as the fallback when minutes are missing.
- Items usually appear at two meetings (Introduction, then Action ~2 weeks later); "Immediate action" items appear once; consent-agenda items are approved en bloc.

---

## 2. Pipeline design

Everything lives in `extractors/sps_web/` (Python, run as `python3 -m extractors.sps_web.<module>` from the repo root; pdftotext/ocrmypdf via subprocess like the fiscal extractors). Generated data goes to `out_sps_web/` (gitignored by `out_*`); the owner promotes finished raw corpora to `data/sps/board/` and GCS.

```
out_sps_web/
  manifest/meetings.jsonl        one row per meeting (date, type, era, source url(s))
  manifest/documents.jsonl       one row per document (meeting, kind guess, source url, fetch recipe, wayback ts)
  raw/<era>/<YYYY-MM-DD>/<file>  downloaded bytes, plus <file>.prov.json (source url, fetch url, fetched_at, sha256, http status, wayback ts)
  text/<era>/<YYYY-MM-DD>/<file>.txt   pdftotext -layout (OCR'd when text layer empty), page breaks kept (\f)
  items/<YYYY-MM-DD>.jsonl       segmented agenda items (see schema)
  contracts/extracted.jsonl      LLM extraction output, one row per (item, document)
  contracts/contracts.csv|xlsx   final spreadsheet
  qa/                            sample sheets, reconciliation reports
```

Stages (each idempotent, keyed by sha256/URL so reruns skip done work):

1. **inventory** — build `meetings.jsonl` + `documents.jsonl` from the five sources; resolve era overlaps (prefer live WP copies over Wayback copies of the same file; keep both URLs as provenance).
2. **fetch** — download with a polite rate limit (1 req/s to seattleschools.org and SharePoint; ≤0.5 req/s to Wayback with backoff on 429/5xx), cache, checksum, provenance.
3. **text** — `pdftotext -layout`; if <50 chars/page, `ocrmypdf --skip-text` then re-extract; `.doc/.docx` via `textutil`/`pandoc`. Classify each doc: `agenda | minutes | bar | warrants | personnel | presentation | other` from filename codes + first-page cues.
4. **segment** — parse agendas and minutes into items: `{meeting_date, item_no, section (consent/action/introduction/immediate), title, body, motion_text, result (approved/failed/postponed/removed/introduced), vote, page_start, page_end, source_doc}`. Rule-based per era with fixtures.
5. **extract** — for items that match the contract pre-filter (regex over title/body: contract|agreement|amendment|change order|purchase|PO |award|RFP|RFQ|bid|lease|MOU|interlocal|final acceptance|renewal|vendor), fill the row schema: `vendor_name, vendor_raw, action_type (new|amendment|change_order|renewal|final_acceptance|purchase|other), amount, amount_kind (not_to_exceed|revised_total|increase|final|annual|unspecified), prior_total, revised_total, contract_id, po_number, term_start, term_end, department, program_or_project, fund (general|BEX|BTA|capital|ASB|grant|other), funding_source_text, procurement_method, board_action, vote, immediate_action (bool), citation {doc_url, page}, extractor (regex|llm)`. **Two passes, item text only (not whole documents):** (a) a deterministic regex extractor over the motion text — modern minutes are formulaic ("…contract amendment with X in the amount of $Y, for a revised total contract amount of $Z…") and should fill vendor/amount/amount_kind/action_type for most post-2016 rows; (b) an in-session subagent pass over only the residual items the regex could not fill or that a validator rejected. Fields that live only in BARs (contract_id, term, fund, procurement_method) are an optional later pass, not on the critical path.
6. **link** — normalize vendor names (canonical + aliases table), pair introduction↔action rows into one contract action (keep both citations), chain amendments/change orders to the parent contract by contract_id/vendor/project.
7. **publish** — `contracts.csv`/`.xlsx` with one row per board action, plus a `vendors.csv` rollup; load to BigQuery `sps_board.contract_actions` (+ `documents`, `meetings`) via the existing schema/AVRO stack; write `COVERAGE.md` and a guide in `docs/guides/BOARD_CONTRACTS.md`.
8. **qa** — sample 150 rows stratified by era, verify against the cited page; reconciliation checks (every meeting has ≥1 minutes or agenda; every action row has a citation that resolves; amounts parse; intro/action pairing rate).

**Cost estimate (revised).** Volumes: ~1,100 meetings → roughly 6–9k contract-like items after the pre-filter; a minutes item is ~150–300 tokens. No Claude API key is used on the critical path.

| Step | Work | Tokens | Cost |
|---|---|---|---|
| Regex pass (E1) | all 6–9k items | 0 | CPU only |
| In-session residual (E2) | assume 20–30% of items miss the regex → ~1.5–2.5k items, batched 100/subagent → 15–25 `haiku` runs at ~30k in / ~15k out each | ~1.0–1.3M total | on the Claude Code plan; API-equivalent ≈ $2–3 at Haiku rates, ≈ $10 if everything escalates to Sonnet |
| Coordination (this session, Fable) | dispatching ~25 batches, reading ≤20-line reports | ~50–100k | ≈ $1–3 equivalent |
| Optional BAR detail pass (E3) | ~3–4k BARs × first 6 pages ≈ 3k tokens | ~10–12M | in-session ≈ 120 `haiku` runs (heavy on plan quota, spread over days) **or** API Batch with Sonnet 5 ≈ $25 / Opus 5 ≈ $65 |

Practical ceiling for the required work is therefore a few dollars of API-equivalent usage, all of it inside the plan's rate windows; the only real constraint is the 5-hour usage window if all E2 batches are fired at once — spread them over two or three sessions if needed. The earlier estimate ($130–260) assumed feeding whole documents to Opus through the API; that path is kept as Appendix A only for the optional BAR pass.

---

## 3. Task cards for subagents

Model key (Agent tool `model` field): **haiku** = mechanical, well-specified; **sonnet** = write/run code from a clear spec; **opus** = design judgment, messy heuristics, review; **fable** = highest-stakes verification. Each card is self-contained; give the subagent this file plus the card. Cards in the same phase can run in parallel; phases are sequential unless noted.

### Phase A — inventory (parallel)

**A1. WP inventory (sonnet)** — `inventory_wp.py`. Page the `board_meeting` REST endpoint, resolve `school_year` and meeting-type taxonomies, parse every `<a>` in `content.rendered` into document rows with link text, href, host class (`wp-upload | sharepoint | sps-page | youtube | other`), and a fetch recipe (`direct` for wp-content; `sharepoint_download` with the extracted `<TOKEN>` for `:b:` links). Emit `meetings.jsonl` and `documents.jsonl` rows tagged `era=wp`. Acceptance: 443 meetings; ≈2,175 wp-upload PDFs and ≈1,830 SharePoint tokens; zero unparsed hrefs left uncategorized.

**A2. Wayback inventories (sonnet)** — `inventory_wayback.py`. Three CDX pulls (Blackboard `UserFiles/…/School Board/*`, legacy `/area/board/*`, `spsarchivepublic.seattleschools.org/*`), keep best capture per URL (prefer status 200, latest timestamp), decode meeting date from folder/filename (`MMDDYY`, `MMDDYYYY`, `YYYYMMDD`, `YYYY-MM-DD` — all four occur), skip `Friday Memos`, `Policies`, `Procedures`, `Maps`, `Annual Reports`, `committees` (flag committees for a later pass). Tag `era=blackboard|legacy|archive`. Acceptance: counts within 10% of Section 1; every row has a meeting date or is written to `manifest/undated.jsonl` for review.

**A3. Merge + coverage matrix (opus)** — `inventory_merge.py`. Union A1+A2 into one meeting list keyed by date+type; dedupe documents that exist in both WP and Blackboard (same filename or same sha256 after fetch); produce `qa/coverage_matrix.md` — rows = school years 2005-06…2026-27, columns = #meetings, has-agenda, has-minutes, #BARs, source(s) — and list gaps. Decide the era-precedence rules and write them down in the module docstring.

### Phase B — fetch (after A)

**B1. Fetcher (sonnet)** — `fetch.py`. One fetcher with per-host rate limits and retries, three recipes (`direct`, `sharepoint_download`, `wayback_raw`), atomic writes, sha256, `.prov.json` per file, resume support, `--era`/`--year` filters, summary report. Honor `robots.txt`. Acceptance: dry-run count matches manifest; a 20-file smoke test per recipe returns `application/pdf` bytes (check `%PDF` magic); non-PDF responses are recorded, not silently saved.

**B2. Run the crawl (haiku)** — run B1 era by era (WP first — it is live and fast; then Blackboard 11-12→15-16; then legacy; then archive), watch for 429s, rerun until the manifest is fully fetched or every remaining failure is classified (404 on all captures / login wall / non-PDF). Report bytes and counts per era. Expect ~10k files, ~5–8 hours wall clock with the rate limits.

### Phase C — text + classification (after B, parallel by era)

**C1. Text extraction (sonnet)** — `totext.py`: pdftotext -layout with form-feed page markers, OCR fallback via `ocrmypdf` for image-only scans (common in 2005–2010), `.doc/.docx` handling, per-file stats (pages, chars/page, ocr=yes/no). Acceptance: every raw file has a `.txt` or an entry in `qa/text_failures.jsonl`.

**C2. Document classifier (sonnet)** — `classify.py`: filename codes (`_Minutes`, `_Agenda`, `C01/SC01/A01/I01`, `actionreport`, `warrant`) plus first-page cues ("Board of Directors — Minutes", "Board Action Report", "Agenda"). Output `kind` and confidence into `documents.jsonl`. Hand-check 30 random per era. Acceptance: ≥97% on the hand-checked set.

### Phase D — segmentation (after C)

**D1. Segmenter design + fixtures (opus)** — pick 3 meetings per era (2007, 2010, 2013, 2016, 2019, 2023, 2025), hand-write the expected item list for each (`tests/fixtures/items/`), then write `segment.py` with one parser per format family (legacy 2-page agenda; legacy minutes; Blackboard `YYYYMMDD_Agenda`; WP-era minutes; modern minutes with numbered business items). Items get `page_start/page_end` from form-feed counting so citations are page-accurate. Acceptance: fixtures pass; on the full corpus, ≥95% of meetings with minutes yield ≥1 business item, and the distribution of items/meeting has no era with a suspicious dip (log it in `qa/segmentation_report.md`).

**D2. Segmentation run + triage (sonnet)** — run D1 over the corpus, triage the failures into parser bugs vs. genuinely itemless docs (work sessions, retreats), fix the bugs, document the rest.

### Phase E — extraction (after D)

**E1. Pre-filter + regex extractor + validator + gold set (opus)** — `extract.py`. (1) The contract pre-filter regex (Section 2). (2) A rule-based extractor over each item's `motion_text`/`body` with named patterns for the recurring formulas: `with <Vendor> in the amount of $X`, `not to exceed $X`, `for a revised total contract amount of $Y`, `Change Order No. N … <Vendor>`, `Final Acceptance of <contract/PO> with <Vendor>`, `amendment … with <Vendor>`, `purchase … from <Vendor>`, plus legacy-era variants found in the 2007–2015 fixtures. It sets `action_type`, `amount`, `amount_kind`, `prior_total`/`revised_total`, `vendor_raw`, `board_action` (from the minutes result), `immediate_action`, `citation` (doc + page from the segmenter), `extractor="regex"`. (3) A validator every row must pass regardless of extractor: amounts parse and are non-negative; `revised_total ≥ amount` for amendments; `vendor_raw` appears verbatim in the item text; citation page ≤ page count; `action_type` consistent with keywords. (4) A **gold set** of 60 hand-labelled items (≥8 per era, every `action_type`) in `tests/fixtures/gold/`; report regex coverage (share of pre-filtered items fully filled) and precision on the gold set. Target: regex fills ≥70% of post-2016 items with 100% gold precision on amount and vendor; anything it can't fill it leaves `null` rather than guessing. Emit `contracts/residual.jsonl` = items with any required field null or a validator failure.

**E2. In-session residual extraction (haiku, escalate to sonnet)** — no API key. Split `residual.jsonl` into batches of ~100 items (`contracts/batches/NNN.jsonl`). For each batch launch one subagent (explicit `model: "haiku"`) whose prompt is the row schema, the extraction rules from E1 (cite a page for every money field; vendor string must be copied verbatim from the text; `null` when absent; never infer), and the batch file path; it writes `contracts/batches/NNN.out.jsonl` and returns only a one-line count (`n_in n_out n_null_vendor`). Run the E1 validator on each output; items that fail go into a second-round batch run with `model: "sonnet"`; anything failing twice goes to `contracts/manual_review.jsonl`. Launch 4–6 batches at a time, not all at once, to stay inside the plan's usage window. Merge regex + LLM rows into `contracts/extracted.jsonl` with `extractor` recorded per row. Expect 15–25 haiku runs and a handful of sonnet reruns.

**E3. Optional BAR detail pass (haiku; or Appendix A)** — only after Phase H confirms the core rows: for action rows with a linked BAR, extract `contract_id, po_number, term_start, term_end, department, fund, funding_source_text, procurement_method` from the BAR's first 6 pages, same batch/validator mechanics as E2 (≈120 runs of 30 BARs), or via the API Batch path in Appendix A if plan quota is the constraint. Skip entirely if the vendor/amount/date rows already answer the analysis questions.

### Phase F — linking + normalization (after E)

**F1. Vendor normalization (opus)** — `vendors.py`: strip suffixes (Inc/LLC/Corp), casefold, known aliases (e.g. "CHILD" ↔ "Children's Institute of Learning Differences", "KCDA", "NASPO ValuePoint / WEX Bank"), cluster near-duplicates with a string-similarity pass and emit `vendors_review.csv` for human confirmation before applying. Never merge automatically below a high threshold.

**F2. Intro↔action pairing and amendment chains (opus)** — `link.py`: pair introduction and action rows (same title/vendor within 60 days), producing one `contract_action` row whose `board_action` comes from the action-meeting minutes and whose detail comes from the BAR; chain amendments/change orders/final acceptances to a parent by `contract_id`/`po_number`, else vendor+project. Output a `chain_id` and `sequence`. Log every unpaired action and every orphan amendment.

### Phase G — publish (after F)

**G1. Spreadsheet + BigQuery (sonnet)** — `publish.py`: `contracts.csv`/`.xlsx` (one sheet of actions, one of vendors rolled up by year, one of documents), citation column as a clickable URL + page; a SAFS-style schema module (`schemas.py`) so the tables load via the existing AVRO/BigQuery stack into dataset `sps_board`. Add a row to `docs/README.md`'s source table.

**G2. Docs (sonnet)** — `docs/guides/BOARD_CONTRACTS.md` (how to rerun, era gotchas, the pairing/chaining rules, NULL conventions) and `extractors/sps_web/COVERAGE.md` (years/meetings/document kinds present vs. missing, and why — spsarchivepublic outage, thin 2011-12, pre-2005 offline only).

### Phase H — QA (after G; final gate)

**H1. Citation audit (fable)** — draw a stratified sample of 150 action rows (≥15 per era, oversample amendments and change orders), open each cited PDF page, and confirm vendor, amount, amount_kind, action_type, and board_action. Record precision per field per era in `qa/audit.md`. Anything under 97% on amount or vendor goes back to E1 with the failing examples; anything under 95% on action_type/board_action goes back to D1/F2.

**H2. Reconciliation (opus)** — checks that don't need a human: every meeting has ≥1 agenda or minutes or is listed in COVERAGE as missing; every row's citation URL resolves (HEAD) and page ≤ page count; amounts are non-negative and `revised_total ≥ amount` for amendments; the count of action rows per year is plotted and any year that drops >50% vs. neighbors is explained by COVERAGE or flagged.

---

## 4. Practicalities

- Rate limits are the schedule: budget a day of unattended crawling. Wayback in particular throttles hard; back off on 429 and never parallelize beyond 2 connections there.
- The district's SharePoint share links are anonymous today; if they stop working, the `guestaccess.aspx` path in Section 1 can also be used, and Wayback has captures of some. Download everything early.
- Keep raw bytes forever (they are the citations). Promote `out_sps_web/raw/` to `data/sps/board/` and GCS once Phase B is done, so reruns don't re-crawl.
- Commit style for this work: `Board contracts: <phase> -- <name>` (mirrors the fiscal parser convention).
- Owner decisions still open: whether to include committee (A&F/Operations) packets in a second pass, and whether purchases below the board-approval threshold (visible only in warrant reports) are in scope.
- Model discipline for whoever coordinates: every Agent/Workflow call passes an explicit `model`; never use `subagent_type: "fork"` (forks inherit the coordinator's model); subagents write results to files and return ≤20-line reports so coordination stays thin.

---

## Appendix A — API Batch path (optional, for E3 only)

Kept for the BAR detail pass if plan quota turns out to be the bottleneck. Not needed for E1/E2.

- Client: `anthropic` Python SDK, Message Batches API (`client.messages.batches.create`), `custom_id = <meeting>-<item>`, results keyed by `custom_id` (they arrive unordered).
- Model: `claude-sonnet-5` is sufficient for BAR field lookup (≈ $25 for ~11M input tokens at batch rates); use `claude-opus-5` (≈ $65) only if a Sonnet sample underperforms on the gold set.
- Output: strict schema via `output_config.format` (`client.messages.parse()`), same validator as E1, request/response ids stored per row for provenance.
- Truncate each BAR to its first 6 pages (fiscal impact and summary are up front); require a page citation per non-null field; forbid vendor names not present in the text.
