# SPS board-approved contracts — data guide & gotchas

One row per Seattle School Board **contract action** — new contract,
amendment, change order, renewal, or final acceptance — from board minutes
and agendas, 2004-05 → present, each with a primary-source citation (a
clickable URL + page). Built by the `extractors/sps_web/` pipeline, phases
A through G1; see the module docstrings for full mechanics — this guide is
the consumer-facing summary. The crawl and extraction pipeline are
complete: **1,894 board-action rows**, from **6,452** segmented business
items across **996** meetings with usable minutes/agenda text (out of
1,023 meetings in the manifest), **2,862** admitted as contract-like,
**1,954** filled by the regex pass and **902** by the LLM residual pass (8
rows unresolved after two LLM rounds, in `manual_review.jsonl`).

**BigQuery has not been loaded.** `extractors/sps_web/publish.py` (task G1)
and `schemas.py` exist and have been run without `--bq`: the spreadsheet
outputs are final and in `out_sps_web/publish/`. Loading BigQuery dataset
`sps_board` requires `--bq` and BigQuery credentials — the module docstring
is explicit that this is **the repo owner's call to run, not something CI
or an agent should do**. Until then, `out_sps_web/publish/contracts.csv` /
`.jsonl` are the ways to query this data outside a spreadsheet.

## 1. Where the files are

| File | What |
|---|---|
| `out_sps_web/publish/contracts.csv` | the `actions` sheet, flat, one row per board action — **this is the dataset** for most consumers |
| `out_sps_web/publish/contracts.xlsx` | three sheets: `actions`, `vendors` (rolled up by vendor × school year), `documents` (cited documents only) |
| `out_sps_web/publish/contracts.jsonl` | action rows, machine-readable, nested `citations` kept (vs. the flattened `citation_1_url`/`citation_2_url` columns in the CSV/XLSX) |
| `out_sps_web/publish/contracts_vendors.csv`, `contracts_documents.csv` | the other two sheets, standalone |
| `out_sps_web/publish/avro/*.avro` | `contract_actions.avro`, `vendors.avro`, `documents.avro` — validated with `fastavro`, dry-run only (`--bq` not passed) |
| `out_sps_web/publish/README.md` | generated summary: row counts, action_type/vendor totals, full column dictionary — regenerates with `publish.py` |
| **not yet loaded** | BigQuery `sps_board.contract_actions` / `.vendors` / `.documents` (project `sps-btn-data`) — owner runs `publish.py --bq` when ready |

Upstream (pre-publish) files, useful for debugging or a from-scratch
analysis: `out_sps_web/contracts/contract_actions.jsonl` (F2's un-flattened
output, publish.py's direct input — every field publish.py reads is
documented in §3 below), `extracted.jsonl` (E1/E2, one row per admitted
*item*, introduction and action still separate rows), `vendors.jsonl` /
`vendor_map.jsonl` (F1's canonical vendor dimension), and
`extractors/sps_web/vendor_aliases.csv` (the human-editable alias table,
checked into git).

QA reports (regenerate a number in this guide by rerunning the named
module): `qa/coverage_matrix.md` (A3), `qa/classify_report.md` (C2),
`qa/segmentation_report.md` (D1), `qa/extract_report.md` (E1),
`qa/e2_report.md` (E2), `qa/vendors_report.md` (F1), `qa/link_report.md`
(F2), `qa/reconcile_report.md` (H2, all 7 checks — see §10).

## 2. How to rerun end to end

All commands run from the repo root as `python3 -m extractors.sps_web.<module>`
(package-relative imports, per this repo's CLAUDE.md convention). Every
module is idempotent/rerunnable and reads only read-only upstream outputs.

```console
# Phase A -- inventory
$ venv/bin/python3 -m extractors.sps_web.inventory_wp
$ venv/bin/python3 -m extractors.sps_web.inventory_wayback              # or --era blackboard/legacy/archive
$ venv/bin/python3 -m extractors.sps_web.inventory_merge

# Phase B -- fetch
$ venv/bin/python3 -m extractors.sps_web.fetch                          # all manifests, resumable
$ venv/bin/python3 -m extractors.sps_web.resolve_sharepoint_names       # names 2021-22+ SharePoint PDFs

# Phase C -- text + classify
$ venv/bin/python3 -m extractors.sps_web.totext
$ venv/bin/python3 -m extractors.sps_web.classify

# Phase D -- segment into business items
$ venv/bin/python3 -m extractors.sps_web.segment

# Phase E -- extract contract facts
$ venv/bin/python3 -m extractors.sps_web.extract                        # regex pass; writes contracts/residual.jsonl
# ... E2 (LLM residual pass) is NOT a module -- it's subagent batches over
# contracts/batches/NNN.jsonl, merged back with:
$ venv/bin/python3 -m extractors.sps_web.e2_merge --batches out_sps_web/contracts/batches --round 1
$ venv/bin/python3 -m extractors.sps_web.e2_merge --batches out_sps_web/contracts/batches --round 2   # for contracts/rerun/*.jsonl

# Phase F -- normalize + link
$ venv/bin/python3 -m extractors.sps_web.vendors                        # writes vendors_review.csv for human triage
$ venv/bin/python3 -m extractors.sps_web.link                           # -> contract_actions.jsonl

# Phase G -- publish
$ venv/bin/python3 -m extractors.sps_web.publish                        # spreadsheet + AVRO (dry-run)
$ venv/bin/python3 -m extractors.sps_web.publish --bq                   # ALSO loads BigQuery -- owner-run only

# Phase H -- QA (no code change; read the report)
$ venv/bin/python3 -m extractors.sps_web.reconcile                      # -> qa/reconcile_report.md
```

Rerunning any single module only touches the paths it owns (documented at
the top of each module).

### Fetch mechanics you need if you touch `fetch.py` or debug a stuck crawl

- **Rate limits, per host, on request *starts*** (independent of thread
  count): `www.seattleschools.org` and `seattleschools.sharepoint.com` — 1
  req/s; `web.archive.org` — 0.5 req/s, ≤2 concurrent connections. 429/5xx/
  connection errors retry with exponential backoff honoring `Retry-After`;
  after 5 tries the row is logged to `fetch_failures.jsonl` (append-only
  across runs) and left unfetched, not partially written.
- **`robots.txt`** for `www.seattleschools.org` allows everything the
  pipeline touches except `/wp-admin/`.
- **Three fetch recipes**, keyed per document row (`fetch.kind`):
  - `direct` — plain GET (2016-17 → 2020-21 wp-content PDFs).
  - `sharepoint_download` — GET
    `https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365/_layouts/15/download.aspx?share=<TOKEN>`
    (2021-22 → present). **Never follow the plain `:b:/s/...` share link
    directly — it bounces to a Microsoft login page.** `download.aspx`
    returns the PDF bytes with *no redirect*, which is also why the real
    filename is unrecoverable from the fetch response — see
    `resolve_sharepoint_names.py` below. 3 documents (6 retry attempts) are
    permanently login-walled this way and stay unfetched.
  - `wayback_raw` — GET `http://web.archive.org/web/<timestamp>id_/<original>`
    (`id_` = raw original bytes, no Wayback chrome). A 404 retries once
    against `http://web.archive.org/web/2id_/<original>` (asks for the
    *nearest* available capture of that exact URL instead of an exact
    timestamp).
- **`resolve_sharepoint_names.py`** recovers the real path/filename for
  `sharepoint_download` rows (needed by `classify.py`'s filename rule) by
  hitting a *different* endpoint that does redirect:
  `https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365/_layouts/15/guestaccess.aspx?share=<TOKEN>&download=1`
  → redirects to `.../Shared Documents/School Board/Board Meetings/<YY-YY>/<meeting>/<real filename>.pdf?ga=1`.
  A token that doesn't resolve answers 200 with an HTML login page **at the
  same URL** (no redirect at all) — that is the "unresolved"/login-walled
  case, distinct from a network failure.
- **8 legacy 2008 presentation PDFs are permanently unrecoverable** — every
  Wayback capture of them truncates at ~130 KB (`IncompleteRead(130770/130771
  bytes read, N more expected)` regardless of retry), so the archived copy
  itself is corrupt, not just slow. Logged in `fetch_failures.jsonl` under
  `unexpected_error`/`connection_error`; nothing downstream will ever pick
  these up short of finding another copy.
- **Wayback CDX pulls are cached** under `manifest/cdx_cache/` so rerunning
  `inventory_wayback.py` never re-hits archive.org unless you pass
  `--refetch-cdx`. CDX itself throttles hard — ≥2s between requests, backoff
  on 429/5xx *and* on a plain timeout (both observed live).

## 3. The citation URL rule (`publish.py`)

A citation names a `doc_id` and a page range. `publish.py` resolves it to
the URL that should live in the spreadsheet — the **primary source**, not
necessarily the URL the document was actually fetched from:

- `fetch.kind` is `direct` or `sharepoint_download` — the document is
  still (or was, anonymously) reachable directly from
  seattleschools.org/SharePoint. `source_url` *is* that live/share URL, so
  it's used as-is.
- `fetch.kind == "wayback_raw"` — the live URL is dead (that's why it had
  to come from the Wayback Machine); `source_url` would 404 today.
  `fetch.url` — the `.../web/<ts>id_/<original>` URL — is used instead;
  `id_` serves the original bytes, unlike the `.../web/<ts>/` form, which
  serves a Wayback-rewritten replay page.

The cited page is appended as a `#page=N` fragment (`N` = the citation's
`page_start`), which most browsers' and PDF viewers' built-in PDF renderers
honor by jumping straight to that page. In the CSV/XLSX these are
`citation_1_url`/`citation_1_page` and `citation_2_url`/`citation_2_page`
(second citation only present when the row is paired — see §5). The
reconciliation check (§10, check 2) verified all 2,862 citations resolve
with pages in bounds; a 30-document live sample all returned HTTP 200.

## 4. The row schema (`actions` sheet / `contract_actions.jsonl`)

One row per board **action** (introduction and action-meeting rows for the
same item are already folded into one — see §5). Full column dictionary
(also regenerated verbatim in `out_sps_web/publish/README.md`):

**Identity / where it happened**
`action_id` (stable hash, `<action date>-<item_no>-<8 hex>`, unique across
all 1,894 rows), `date` (meeting date), `school_year`, `title`.

**What the board did**
`board_action` (`introduced`|`approved`|`removed`|`withdrawn`|`unknown`),
`vote`, `immediate_action` (bool — true if the board acted at a single
meeting rather than introduce-then-vote).

**The contract fact**
`vendor_raw` (verbatim substring of the source text — never inferred),
`vendor_canonical` (F1's canonical display name), `vendor_class`
(`government`|`cooperative`|`contractor`|`nonprofit`|`school_placement`|
`labor_union`|`unknown` — `not_a_vendor` rows are excluded from the
`vendors` sheet but their `vendor_raw` can still appear on an `actions` row
with `vendor_class=null`), `action_type` (`new`|`amendment`|
`change_order`|`renewal`|`final_acceptance`|`purchase`|`other`), `amount`,
`amount_kind` (`not_to_exceed`|`revised_total`|`increase`|`final`|
`annual`|`unspecified`), `prior_total`, `revised_total`, `contract_id`,
`po_number`, `term` (`term_start`/`term_end` combined into one `"START to
END"` string, or whichever is present), `department`,
`program_or_project`, `fund`, `funding_source_text`, `procurement_method`
(the last three remain **sparse** — no dedicated BAR-detail extraction
pass has run, PLAN.md's optional Phase E3; they're only filled where the
regex/LLM item-text pass picked them up incidentally).

**Chains**
`chain_id`, `sequence` (0-based order within the chain), `chain_total_latest`
(most recent `revised_total`/`amount` known for the chain as of this action
— naive, see §11).

**Extraction provenance**
`extractor` (`regex`|`llm`), `paired` (bool — an introduction row was
matched and merged into this action row).

**Citation** (§3)
`citation_1_url`, `citation_1_page`, `citation_2_url`, `citation_2_page`.

`contracts.jsonl` (and the upstream `contract_actions.jsonl`) carry a
larger field set — `citations` as a real list, `intro_meeting_id`/
`intro_meeting_date`/`intro_item_no`/`intro_era`, `pair_method`,
`amount_conflict`, `chain_method` (`id`|`vendor_project`|`singleton`),
`chain_size`, `is_root`, `chain_evidence`, `orphan_amendment`,
`vendor_id`/`vendor_id_source`, `era`, `item_no`/`item_code`,
`unpaired_reason` — see `link.py`'s docstring for the complete list if you
need to work below the published sheet.

## 5. How pairing and chaining work

**Intro↔action pairing (F2, `link.py`).** The board usually votes on an item
twice: introduced at one meeting, voted at the next (7–35 days later, modal
gap 14 days). Those are two separate rows in `extracted.jsonl`; `link.py`
folds them into one action row, action-meeting data winning any field
conflict, both citations kept (`citations=[intro, action]`).

- `MAX_PAIR_GAP_DAYS = 60`, `MIN_PAIR_GAP_DAYS = 0` (same-day allowed — some
  minutes record an intro and an "immediate action" of the same item on the
  same page).
- Six match tiers tried strictly in order, each only consulted for
  introductions the higher tiers couldn't place: exact title (≥15 chars,
  same *format family*) → exact title with `(...)` parentheticals stripped
  (catches the 2005-2012 habit of appending the sponsoring committee to
  only one of the two printings) → title-prefix match (≥40 chars, needs
  vendor/amount corroboration unless ≥60 chars alone) → same vendor + exact
  amount (catches items whose title was rewritten between meetings) → the
  same two exact tiers again but relaxed to allow a cross-era pair *inside*
  one of two overlapping-source families (`ERA_FAMILY`, see §9): `legacy`/
  `archive` → `"early"`, and `blackboard`/`wp1620`/`modern` → `"wp"` — a
  pairing straddling the Blackboard/WordPress site transition (Aug 2016) or
  the 2021 SharePoint migration is allowed on an exact-title match once
  same-family candidates are exhausted, but a pairing never crosses
  `"early"` ↔ `"wp"`.
- **A tie kills the pair, on purpose.** If two unclaimed candidates in a tier
  have the same day-gap, the introduction is left unpaired
  (`unpaired_reason`) rather than guessed — a wrong pairing silently merges
  two different contracts, which is worse than a missed one.
- Amount disagreement between the intro and action rows does **not** veto a
  pair; it sets `amount_conflict=true` for QA sampling instead.
- **Final pairing rate: 83.1%** of introductions (968/1,165); by format
  family: legacy 88.8%, modern 91.4%, wp1620 85.5%, blackboard 80.6%,
  archive 75.8% (`qa/link_report.md`). Only one pair corpus-wide rests on
  vendor+amount alone with title similarity < 0.20 (the segmenter gave that
  action row the wrong title — "(action report and attachments edited)").

**Amendment chains (F2, same module).** Groups a `new`/`purchase` root with
its later `amendment`/`change_order`/`renewal`/`final_acceptance` rows into
one `chain_id`.

- `chain_method="id"` — rows share a normalized `contract_id` or `po_number`.
  182 chains / 417 rows.
- `chain_method="vendor_project"` — same vendor **and** either (a) title
  token-Jaccard ≥ 0.60 with ≥2 shared distinctive tokens, or (b) money
  continuity: one row's `prior_total` equals another's `revised_total`/
  `amount` to the cent. 107 chains / 344 rows.
- `chain_method="singleton"` — everything else. 1,133 chains (most
  contracts in this corpus have no amendment on record).
- **Totals: 1,426 chains, 1,894 rows**, size distribution 1→1,133, 2→196,
  3→59, up to one chain of 13 (a long-running renewal series). `qa/reconcile_report.md`
  check 5 confirms every chain's `sequence` is contiguous and no action row
  is claimed by more than one chain.
- `orphan_amendment=true` marks an amendment/change_order/renewal/
  final_acceptance row whose chain has no `new`/`purchase` row at or before
  it — 477 rows, common and expected pre-2016 (the parent contract
  predates the corpus).

**Source precedence for competing copies of the same meeting** (`segment.py`'s
`source_rank`, upstream of both pairing and extraction): (1) **official
beats unofficial/draft** — Blackboard published `..._Minutes_UNOFFICIAL.pdf`
drafts alongside the copy WordPress later carried as the record, and the
two paginate differently; (2) **`wp` beats `blackboard` beats `legacy`
beats `archive`** (`ERA_RANK`); (3) amended beats official/approved/final
beats revised/updated beats a plain copy; (4) longest text wins (a
truncated/partial scan loses). The documents a winning copy beat are never
discarded — they're recorded on the winning item's `extractor_notes` as
`"alternate copies: <doc_id> (<stem or era>); ..."` (up to 3 listed), so a
fallback source is always one field away if the winning PDF ever goes
missing.

## 6. Vendor normalization workflow (F1, `vendors.py` + `vendor_aliases.csv`)

1. `canonical_key()` folds a raw vendor string automatically: strips
   contract/bid-number award-clause prefixes E1 sometimes swallowed
   ("Contract D5050 to X" → "X"), strips trailing project descriptors,
   casefolds, drops punctuation and legal suffixes (Inc/LLC/Corp/...),
   normalizes common abbreviations, drops a leading "the".
2. `extractors/sps_web/vendor_aliases.csv` (checked into git, hand-maintained,
   507 lines) maps a folded key to a canonical display name and a
   `vendor_class`. **This is the only place a merge or classification
   judgment call is applied automatically** — everything else groups by
   exact folded-key equality. 100 of 633 distinct raw vendor strings are
   currently mapped through an alias row; 533 map by exact key alone.
3. Near-duplicate keys the automatic key-fold didn't unify are only
   *proposed*, in `out_sps_web/contracts/vendors_review.csv` (a disposable
   worksheet holding only *undecided* pairs; 0 as of this run) — nothing
   below a `ratio ≥ 0.92` string-similarity threshold (or `ratio ≥ 0.85`
   with identical first two tokens) is even proposed. **To decide a pair:**
   open the worksheet, set `approve` to `y` (merge) or `n` (never propose
   again) on the row, then rerun `vendors.py`. The decision is harvested
   into the committed, hand-maintained `extractors/sps_web/vendor_merges.csv`
   (`key_a,key_b,decision,…`; 46 decisions: 23 y / 23 n as of 2026-08-25),
   which is the system of record and is applied on every run — so a mark
   survives reruns even after the pair stops being proposed. Rerun then —
   approved pairs merge with `method="cluster"` and the mark carries
   forward on the next regeneration. This queue currently sits unreviewed;
   applying it (a human task) would tighten the vendor dimension before any
   further BigQuery load.
4. `vendor_class` values: `government`, `cooperative`, `contractor`,
   `nonprofit`, `school_placement`, `unknown`, plus `labor_union` (CBAs are
   a large slice of this corpus and are not contractors) and
   `not_a_vendor` (the district itself, project names, bid-number labels,
   and other E1 capture noise — 34 distinct strings, e.g. "Bid No", "XXX").
   `not_a_vendor` rows keep `vendor_id=null` in `vendor_map.jsonl` so
   downstream code can drop them. **87 vendors currently sit in
   `unknown`** (up from 0 before the Blackboard crawl finished — that era
   introduced 2011-2016 vendor strings the alias table hasn't caught up
   with yet); the `vendors_review.csv` queue and `vendor_aliases.csv` both
   need a pass over this era's names before the vendor dimension can be
   called settled.

To add a new alias or fix a misclassification: edit
`extractors/sps_web/vendor_aliases.csv` directly (it's a free-text CSV with a
comment header explaining each column) and rerun `vendors.py`, then
`link.py` and `publish.py` to propagate the new `vendor_id`/`vendor_class`.

## 7. Extraction design: regex-first, LLM for the residual

**Pre-filter (E1).** Every segmented business item is tested against an
`INCLUDE_RE` (contract/agreement/amendment/bid/lease/RFP/etc.) and a set of
named `EXCLUDE_RES` (warrants, minutes-of-minutes, personnel reports, board
policy/resolution titles, revenue acceptance, bargaining, calendar
amendments) — the exclusions run first and are hard vetoes even when an
include keyword also matches. 44.4% of all 6,452 segmented items are
admitted (2,862); a hand-audited 60-item sample (30 admitted + 30 rejected)
scored 100%/100% precision.

**Regex extraction (E1).** ~20 named vendor-anchor patterns and ~14 named
amount patterns (see `extract.py`'s docstring table for the full list with
verbatim corpus examples) walk each item's own text — never the whole
document — filling `vendor_raw`/`amount`/`amount_kind`/`action_type`/
identifiers/terms. **Never guesses**: a field the text does not literally
print stays `null`. When an item names more than one vendor or amount, the
first-anchored pair is kept as primary and the rest recorded in
`extractor_notes` as `extra_vendor:`/`extra_amount:`. Regex coverage
(vendor + amount-or-no-dollar-figure + non-`other` action type, validator
passing) is **68.3% overall (1,954/2,862)**, by format family: modern
80.7%, wp1620 73.1%, blackboard 68.0%, legacy 59.8%, archive 59.6%; 75.5%
for post-2016 items combined (target was ≥70%).

**Validator (`extract.validate()`)**, applied to every row regardless of
which pass produced it:
- amounts parse, are non-negative, and ≤ `AMOUNT_CEILING` ($2B — the source
  really does print typos like "$39,542,000,000" for student transportation;
  anything above the ceiling is rejected as implausible rather than kept);
- `action_type`/`amount_kind` are in the fixed vocabulary;
- an `amount` requires a non-null `amount_kind`;
- for `amendment`/`change_order` rows, `revised_total ≥ amount`;
- `vendor_raw`, every `co_vendors_raw` entry, and every
  `contract_id`/`po_number`/`bid_number`/`rfp_number` must appear **verbatim
  in this item's own text** (case/whitespace-insensitive) — this specifically
  caught the LLM pass leaking an identifier from a neighboring item;
- citation page bounds are sane;
- `action_type` has textual support (e.g. `final_acceptance` requires
  "final acceptance"/"as complete"/"accept the work" somewhere in the item);
- a row with no `amount` is flagged if the item text has a `$` figure
  anywhere (`amount_missing_though_text_has_money`) — the signal that
  routes an item to the LLM residual pass rather than accepting a false
  null. **One deliberate exception**: an LLM row is allowed a null `amount`
  without tripping this check when its `extractor_notes` explains why —
  `malformed_amount:` (the source's own printed figure is corrupted, e.g.
  column-bleed OCR like "$2,345,2922,361,532") or `not_a_contract:` (E1's
  regex admitted the item but it isn't actually a contract action). E1's
  regex pass can't see that distinction; only the LLM pass, reading the
  full item, is allowed to claim it.

**Residual / LLM pass (E2).** Items failing the pre-filter's regex fill or
the validator go to `contracts/residual.jsonl` (889 items this run),
batched ~100/file, run in-session (no API key — one subagent per batch,
`haiku` first, escalate to `sonnet` on validator failure). Same validator,
same "never guess" rule, applied identically to LLM output.
**`e2_merge.py` is idempotent across rounds**: before touching a key's row
in the current batch, it checks whether `llm_rows.jsonl` already has that
key settled at this round or a later one, and if so leaves it completely
alone — not re-validated, not re-added to `rerun/` or `manual_review.jsonl`.
This makes it safe to re-run an old round after adding new batches without
regressing a later round's fixes. Outcome: **902 of 908 residual items
resolved by the LLM pass, 4 in `manual_review.jsonl`** (2 remain genuinely
unaccounted for — the last two rows of the 889 that neither the regex nor
two LLM rounds settled). Combined regex+LLM coverage by era: legacy 99.7%,
archive 100.0%, blackboard 99.9%, wp1620 100.0%, modern 100.0% (`qa/e2_report.md` —
"coverage" here means *some* row exists for the item, not that every field
is filled; see the residual-category breakdown there for what's still
`null` on purpose, e.g. `vendor_unnamed` items where the source literally
says "various vendors").

**Gold set.** 74 hand-labelled items (`tests/fixtures/gold/gold.jsonl`),
resolved against the corpus by `(meeting_id, item_no)` — `char_start` is
advisory only, used to disambiguate the 26 `(meeting_id, item_no)` pairs
that genuinely recur (an item minuted under two roman blocks), since
re-running the segmenter shifts offsets whenever pagination or the chosen
source document changes and re-keying on every run would be busywork that
hides real drift. Scores: **admitted 100%/100%, vendor_raw 100% precision /
92.3% recall (4 mismatches, all real misses, not false vendors), amount
100%/100%, amount_kind 100%/100%, action_type 100%/100%, revised_total
100%/100%, prior_total 100%/100%, contract_id 100%/100%.**

## 8. NULL conventions

Every field is `null`-if-absent, never a placeholder string or zero, with
one deliberate design rule threaded through the whole pipeline:
**a `null` in this dataset means "the source document does not print this
fact in this item," not "the pipeline failed to find it."** Concretely:

- `vendor_raw`/`amount`/every identifier field: `null` unless the exact
  substring is verbatim in the item's own text (never inferred from title,
  neighboring items, or an unparsed Board Action Report).
- `fund`/`funding_source_text`/`procurement_method`/`term`: usually `null`
  — these live mostly in Board Action Reports, and the BAR detail pass
  (PLAN.md's optional Phase E3) has not been run; what's non-null here was
  picked up incidentally by the item-text regex/LLM pass, not
  systematically.
- `amount` can be `null` on an LLM-sourced row *even when the item text has
  a dollar figure*, specifically when `extractor_notes` carries
  `malformed_amount:` or `not_a_contract:` (§7) — check that field before
  treating a null amount as a missed fact.
- `vendor_class` is `null` on an `actions` row whose `vendor_raw` maps to a
  vendor not (yet) classified (§6's 87 `unknown` vendors) — don't assume a
  non-null `vendor_raw` implies a resolvable class.
- `chain_evidence`/`amount_conflict`-detail fields are populated only on
  the specific rows the QA report is meant to surface.

## 9. Format families / era gotchas (from `segment.py`/`extract.py`)

Five reporting format families now cover the whole corpus, keyed off the
document's format regardless of which host the file happened to survive
on: `legacy` (2004-05 → 2010-11 `/area/board/` PDFs), `archive` (2006-2012
spsarchivepublic "edited agendas"), `blackboard` (2011-12 → 2015-16,
`YYYYMMDD_Agenda.pdf`/`YYYYMMDD_Minutes.pdf`), `wp1620` (2016-17 →
2020-21), `modern` (2021-22 → present). `era_of(doc_era, meeting_date)`
assigns `wp` and `blackboard` documents to a family **by meeting date, not
by which site hosted the surviving file**: since the Blackboard crawl
landed, many 2016-17 → 2020-21 meetings take their minutes from the
Blackboard copy (WordPress only ever carried the agenda for some of them),
and those minutes are `wp1620`-format in every respect that matters —
`legacy` and `archive` keep their own family regardless.

- **The `blackboard` format family (2011-12 → 2015-16)** uses the same
  three-level outline as every other era (Business Action Items → Consent/
  Removed/Action/Introduction), item bodies "Approval of this item will
  ...", and right-margin annotations `(action)`/`(introduction)`/
  `(introduction/action)` — structurally the same as the `archive`
  agendas. Its *minutes* (`YYYYMMDD_Minutes.pdf`) use the same outline
  and annotations plus a per-item outcome sentence ("The motion passed
  unanimously."), so no separate parser was needed; fixtures at 2013-01-23,
  2014-03-19, 2015-09-23. Item codes (C01/SC01/A01/I01) come from sibling
  BAR filenames, not the agenda/minutes text itself.
- **`meeting_id` is the meeting where the item's *outcome* was recorded (the
  action meeting for a paired row), not the subject the document is about.**
  WP-era minutes filenames are `C01_<posting meeting>_Minutes_<meeting the
  minutes describe>` — the manifest's naive `meeting_id` is the posting
  meeting; `segment.py` re-derives the true subject date (`subject_date`)
  before assigning items to a meeting.
- **BAR filename dates are the introduction date, not the action date.** A
  Board Action Report keeps the item code of the meeting where the item was
  *introduced* even when it's re-linked at the later action meeting — 79
  consent items in this corpus have `I` as their only sibling filename
  code. `section` therefore always comes from the document's own
  subsection heading, never from the filename's item-code letter.
- **Consent items removed and re-voted appear once, not twice.** An item
  pulled from consent and re-voted under "Items Removed from the Consent
  Agenda" is emitted only from that removed-section appearance
  (`section="action"`, a note records it was removed from consent); the
  original consent-agenda copy is suppressed so Phase E can't double-count
  it. An item removed with *no* re-vote keeps `board_action="removed"`.
- **The 2007-11 minutes hole.** 2007-08 through 2010-11 have agendas for
  nearly every meeting but very few real minutes (1–3 minutes documents per
  year vs. 23–52 agendas) — see COVERAGE.md. Agendas record no
  `board_action` or `vote` (pre-meeting documents), so most rows from those
  years carry `board_action="introduced"` or `unknown` even for items that
  plainly passed. Where the agenda's item doesn't match a title already
  pulled from the (rare) minutes, `segment.py` inserts it with
  `source_kind="agenda"` and a note, at its printed position — it never
  duplicates a minutes item.
- **Legacy/archive/blackboard agendas rarely carry a dollar figure at
  all** — the vendor and the amount usually live only in the (often
  thinner) minutes or in a Board Action Report that isn't fully parsed
  (Phase E3). Nothing in this pipeline guesses at what the agenda doesn't
  print — those rows stay `null` rather than being backfilled from a BAR
  nobody read.
- **Legacy PDFs sometimes carry a wrong date in the page header** — a
  filename `010908agenda.pdf` was seen to print "January 9, **2007**" on the
  page itself. The *filename* date wins for meeting assignment in this era.
- **Blackboard also published draft copies.** `..._Minutes_UNOFFICIAL.pdf`
  drafts exist alongside the official copy WordPress later carried, and the
  two paginate differently — `is_draft()` matches `(?:un[- _]?official|draft)`
  in either the filename or the first 1,500 characters of text, and
  `source_rank` always prefers the official copy (§5).
- **Phrasing shifts across eras**: 2005-06 minutes/agendas file introduction
  items under a roman "New Business" heading enumerated **A., B., C.** (not
  1., 2., 3.); modern minutes' outcome sentence is "This motion was
  approved unanimously (Directors ... voted yes)" where 2016-2021 says
  "This motion passed with a vote of 5-0-1 (...)" and legacy says the terse
  "This item passed unanimously."; committee annotations like "(Ops,
  September 5, for Approval)" appear between title and description only in
  the 2016-17 → 2020-21 window.

## 10. Reconciliation (H2) — what's been verified

`extractors/sps_web/reconcile.py` runs 7 automated checks with no human
sampling; all pass except one WARN (`qa/reconcile_report.md`):

1. **Meeting coverage (WARN)** — 26/1,023 meetings (2.5%) have fetched,
   classified documents but none of them is agenda/minutes kind (e.g. only
   a Board Action Report or a presentation deck survives for that meeting).
   These are real, permanent gaps, not a pending-crawl artifact — see
   COVERAGE.md for the breakdown.
2. **Citation resolution — PASS.** All 2,862 citations (432 unique cited
   documents) resolve, pages are in bounds, URLs are well-formed; a 30-doc
   live HTTP sample all returned 200.
3. **Money sanity — PASS.** No negative or > $2B amounts, no
   `amendment`/`change_order` row with `revised_total < amount`, no
   `amount` without an `amount_kind`; of the 3 rows carrying `prior_total`
   + `amount` + `revised_total` all at once, 0 mismatches on
   `prior_total + amount == revised_total`.
4. **Vendor mapping — PASS.** All 1,369 `vendor_raw` values on action rows
   map to a known `vendor_id` or are flagged `not_a_vendor` — none fall
   through uncategorized.
5. **Pairing/chains — PASS.** 1,426 chains, every `sequence` contiguous, no
   action row claimed by more than one chain, no paired row where the
   introduction is dated after the action.
6. **Time series — PASS.** No school year's action-row or admitted-item
   count drops more than 50% versus both neighboring years.
7. **Key uniqueness — PASS.** `action_id` is unique across all 1,894 rows;
   `(meeting_id, item_no, char_start)` is unique across all 6,452 items.

## 11. Known limitations

- **Naive amount sums double-count.** `amount` mixes not-to-exceed, revised-
  total, increase, and final values, and, before F2 pairing, an
  introduction and its action are two separate rows with (often) the same
  amount printed twice. `vendors` sheet's `amount_sum` is explicitly a
  sort key, not a spend figure. Use `chain_total_latest` for "what is this
  contract worth now," and even that is "last reported total on the record,"
  not audited lifetime spend.
- **4 rows in `manual_review.jsonl`** failed extraction after regex + 2 LLM
  rounds and need a human to read the source page directly.
- **26 meetings have documents but no usable agenda/minutes text**
  (reconcile check 1) — a permanent structural gap, not a pending-crawl
  artifact, since the crawl and text extraction are both complete.
- **Pre-2004-05 is offline-only.** WA State Digital Archives title 551 is
  not online yet ("coming soon"); anything earlier requires a manual request
  to SPS Archives (archives@seattleschools.org, 206-252-0796). Not automatable.
- **committee packets (1,333 Wayback rows) are set aside**, not merged into
  the meeting/document inventory — an open owner decision (PLAN.md §4), so
  A&F/Operations/Curriculum committee-level contract discussion is out of
  scope for this dataset as it stands.
- **No BAR (Board Action Report) detail pass has run** — `contract_id`,
  `term`, `fund`, `procurement_method` are populated only where the item
  text itself happened to print them, not systematically (Phase E3 in
  PLAN.md, explicitly deferred as optional).
- **87 vendors are unclassified** (`vendor_class="unknown"`) — mostly
  Blackboard-era (2011-2016) names the alias table hasn't caught up with
  (§6). All 46 proposed merges have been decided (`vendor_merges.csv`);
  parent/child government pairs (City of Seattle vs its departments, King
  County vs Metro/DDD/Public Health, UW vs its centers) were deliberately
  kept separate.
- **BigQuery has not been loaded** — the owner's call; `--bq` is a flag
  away once ready (§1, §2).

## 12. Anti-patterns

- **Don't `SUM(amount)` across a chain (or across a vendor) expecting a
  spend total.** It double-counts: an amendment's `amount` is the
  *increase*, not the new total, and `revised_total` on the same row is
  already the cumulative figure. Use `chain_total_latest` for "what is this
  contract worth now," and even that is "last reported total on the record,"
  not audited lifetime spend.
- **Don't treat `revised_total` as an increment.** It is the *cumulative*
  contract value after the action, by construction (`a_revised_total`,
  `a_total_contract_amount`, `a_new_total` patterns in `extract.py` all map
  to `amount_kind="revised_total"`). Subtract `prior_total` from
  `revised_total` if you want the increment, and only when both are non-null
  on the *same* row.
- **Don't join on `(meeting_id, item_no)` alone** — pairs recur across
  combined-meeting PDFs and same-meeting retaken items; join on
  `(meeting_id, item_no, char_start)` if you need to hit `extracted.jsonl`,
  or just use `action_id` on the published `actions` sheet, which is
  already unique (reconcile check 7).
- **Don't assume a null `board_action`/`vote` means the item failed.** Most
  agenda-sourced pre-2016 rows are `board_action="unknown"` or
  `"introduced"` simply because the agenda is a pre-meeting document that
  never records an outcome — see §9.
- **Don't assume a null `amount` on an LLM row means no dollar figure was
  printed.** Check `extractor_notes` for `malformed_amount:`/
  `not_a_contract:` first (§7, §8) — those are deliberate nulls with a
  reason, not a missed extraction.
- **Don't trust `kind_guess` in the manifest as a document classification.**
  It's A1/A2's cheap filename/link-text guess; `classify.py`'s `kind` (which
  reads the fetched bytes and the SharePoint-resolved filename) is the
  authority — always use `kind`, not `kind_guess`, downstream of Phase C.
- **Don't merge two vendor strings just because they look similar.** Only
  `vendor_aliases.csv` rows and human-approved `vendor_merges.csv` pairs are
  ever merged; a Jaccard/ratio similarity alone is a *proposal*, not a
  merge.

## See also

[`extractors/sps_web/COVERAGE.md`](../../extractors/sps_web/COVERAGE.md) —
per-school-year meeting/document/item/row counts and what's missing and why.
[`extractors/sps_web/PLAN.md`](../../extractors/sps_web/PLAN.md) — the
full pipeline design, source map, and task cards this guide summarizes.
[`out_sps_web/publish/README.md`](../../out_sps_web/publish/README.md) —
generated: current row counts, action-type/vendor dollar totals, full
column dictionary.
