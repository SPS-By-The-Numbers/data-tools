# SPS board-approved contracts — data guide & gotchas

One row per Seattle School Board **contract action** — new contract,
amendment, change order, renewal, or final acceptance — from board minutes
and agendas, 2004-05 → present, each with a primary-source citation (a
clickable URL + page). Built by the `extractors/sps_web/` pipeline, phases
A through G1; see the module docstrings for full mechanics — this guide is
the consumer-facing summary. The crawl and pipeline are complete: **1,976
board-action rows** (891 of them from meetings since 2016-08-01), from
**6,452** segmented business items across **996** meetings with usable
minutes/agenda text (out of 1,023 meetings in the manifest), **2,862**
admitted as contract-like — **1,939** filled complete by the regex pass,
**923** sent to the LLM residual pass (of which 915 resolved, **8** rows
remain in `manual_review.jsonl`) — then run through the E3 Board Action
Report pass (2016+ only) and F1/F2 normalization and linking. 429 tests
pass (`extractors/sps_web/tests/`).

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
| `out_sps_web/publish/contracts.csv` | the `actions` sheet, flat, one row per board action (or per vendor, for a multi-vendor motion — see §6) — **this is the dataset** for most consumers |
| `out_sps_web/publish/contracts.xlsx` | three sheets: `actions`, `vendors` (rolled up by vendor × school year), `documents` (cited documents only) |
| `out_sps_web/publish/contracts.jsonl` | action rows, machine-readable, nested `citations` kept (vs. the flattened `citation_1_url`/`citation_2_url`/`citation_3_url` columns in the CSV/XLSX) |
| `out_sps_web/publish/contracts_vendors.csv`, `contracts_documents.csv` | the other two sheets, standalone |
| `out_sps_web/publish/avro/*.avro` | `contract_actions.avro`, `vendors.avro`, `documents.avro` — validated with `fastavro`, dry-run only (`--bq` not passed) |
| `out_sps_web/publish/README.md` | generated summary: row counts, action_type/vendor totals, full column dictionary — regenerates with `publish.py` |
| **not yet loaded** | BigQuery `sps_board.contract_actions` / `.vendors` / `.documents` (project `sps-btn-data`) — owner runs `publish.py --bq` when ready |

Upstream (pre-publish) files, useful for debugging or a from-scratch
analysis: `out_sps_web/contracts/extracted.jsonl` (E1/E2, one row per
admitted *item*, introduction and action still separate rows),
`contracts/extracted_filled.jsonl` (E3's parallel file — same rows, BAR
fields merged in; **this, not `extracted.jsonl`, is what `vendors.py` and
`link.py` read** once E3 has run), `vendors.jsonl` / `vendor_map.jsonl`
(F1's canonical vendor dimension), and two human-editable, git-tracked
tables: `extractors/sps_web/vendor_aliases.csv` (string→canonical alias
table) and `extractors/sps_web/vendor_merges.csv` (durable y/n cluster-merge
decisions, §7).

QA reports (regenerate a number in this guide by rerunning the named
module): `qa/coverage_matrix.md` (A3), `qa/classify_report.md` (C2),
`qa/segmentation_report.md` (D1), `qa/extract_report.md` (E1),
`qa/e2_report.md` (E2), `qa/bar_fill_report.md` + `qa/bar_llm_report.md` +
`qa/bar_conflicts.jsonl` (E3), `qa/vendors_report.md` (F1),
`qa/link_report.md` (F2), `qa/reconcile_report.md` (H2, all 7 checks — see
§12).

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

# Phase E1/E2 -- extract contract facts from the item text
$ venv/bin/python3 -m extractors.sps_web.extract                        # regex pass; writes contracts/residual.jsonl
# ... E2 (LLM residual pass) is NOT a module -- it's subagent batches over
# contracts/batches/NNN.jsonl, merged back with:
$ venv/bin/python3 -m extractors.sps_web.e2_merge --batches out_sps_web/contracts/batches --round 1
$ venv/bin/python3 -m extractors.sps_web.e2_merge --batches out_sps_web/contracts/batches --round 2   # for contracts/rerun/*.jsonl

# Phase E3 -- fill fields only the Board Action Report carries (2016+ only)
$ venv/bin/python3 -m extractors.sps_web.bar_fill                       # regex pass -> extracted_filled.jsonl + contracts/bar_batches/
# ... optional LLM fallback for rows the regex pass still left null, same
# in-session-subagent mechanics as E2:
$ venv/bin/python3 -m extractors.sps_web.bar_fill --merge-llm

# Phase F -- normalize + link
$ venv/bin/python3 -m extractors.sps_web.vendors                        # reads extracted_filled.jsonl if present; writes vendors_review.csv
$ venv/bin/python3 -m extractors.sps_web.link                           # -> contract_actions.jsonl (explodes multi-vendor rows, §6)

# Phase G -- publish
$ venv/bin/python3 -m extractors.sps_web.publish                        # spreadsheet + AVRO (dry-run)
$ venv/bin/python3 -m extractors.sps_web.publish --bq                   # ALSO loads BigQuery -- owner-run only

# Phase H -- QA (no code change; read the report)
$ venv/bin/python3 -m extractors.sps_web.reconcile                      # -> qa/reconcile_report.md
```

Rerunning any single module only touches the paths it owns (documented at
the top of each module). E3 sits between E2 and F1/F2 and is scoped to
all meeting years (the pass was first scoped to 2016-08-01 forward, then extended on 2026-08-25; see §8) — everything
before Phase E3 in the list above covers the whole corpus back to 2004-05.

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
  itself is corrupt, not just slow.

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
(second citation present when the row is paired — §5); a row with a linked
Board Action Report additionally carries `citation_3_url`/`citation_3_page`
(`role="bar"`, §8). The reconciliation check (§12, check 2) confirmed all
citations resolve with pages in bounds; a live sample all returned HTTP 200.

## 4. The row schema (`actions` sheet / `contract_actions.jsonl`)

One row per board **action** — with two exceptions to "one row": a
multi-vendor motion becomes one row per vendor (§6), and introduction/action
rows for the same item are already folded into one (§5). Full column
dictionary (also regenerated verbatim in `out_sps_web/publish/README.md`):

**Identity / where it happened**
`action_id` (stable hash, `<action date>-<item_no>-<8 hex>`, `-v2`/`-v3`/...
suffix for a multi-vendor member — unique across all 1,976 rows), `date`
(meeting date), `school_year`, `title`.

**What the board did**
`board_action` (`introduced`|`approved`|`removed`|`withdrawn`|`unknown`),
`vote`, `immediate_action` (bool — true if the board acted at a single
meeting rather than introduce-then-vote).

**The contract fact**
`vendor_raw` (verbatim substring of the source text — never inferred, or,
for a BAR-filled row, verbatim in the BAR text — see §8),
`vendor_canonical` (F1's canonical display name), `vendor_class`
(`government`|`cooperative`|`contractor`|`nonprofit`|`school_placement`|
`labor_union`|`unknown` — `not_a_vendor` rows are excluded from the
`vendors` sheet but their `vendor_raw` can still appear on an `actions` row
with `vendor_class=null`), `action_type` (`new`|`amendment`|
`change_order`|`renewal`|`final_acceptance`|`purchase`|`other`), `amount`,
`amount_source` (`minutes`|`bar`|`bar_llm` — where `amount` came from;
empty when `amount` is empty), `amount_kind` (`not_to_exceed`|
`revised_total`|`increase`|`final`|`annual`|`monthly`|`unspecified`),
`prior_total`, `revised_total`, `contract_id`, `po_number`, `term`
(`term_start`/`term_end` combined into one `"START to END"` string, or
whichever is present), `department`, `program_or_project`, `fund`,
`funding_source_text`, `procurement_method` (these last several are much
better filled for 2016+ rows now that E3 has run — see §8 — and remain
sparse before 2016, where no BAR pass has run).

**Multi-vendor** (§6)
`multi_vendor_group` (primary row's `action_id`, repeated on every member;
null on ordinary rows), `multi_vendor_n` (member count), `group_total` (a
joint award's single shared not-to-exceed, repeated on every member row —
**never summed down the column**, see §6/§13).

**Chains**
`chain_id`, `sequence` (0-based order within the chain), `chain_total_latest`
(most recent `revised_total`/`amount` known for the chain as of this action
— naive, see §13).

**Extraction provenance**
`extractor` (`regex`|`llm`), `paired` (bool — an introduction row was
matched and merged into this action row).

**Citation** (§3)
`citation_1_url`/`_page`, `citation_2_url`/`_page`, `citation_3_url`/`_page`
(BAR, when linked).

`contracts.jsonl` (and the upstream `contract_actions.jsonl`) carry a
larger field set — `citations` as a real list, `intro_meeting_id`/
`intro_meeting_date`/`intro_item_no`/`intro_era`, `pair_method`,
`amount_conflict`, `chain_method` (`id`|`vendor_project`|`singleton`),
`chain_size`, `is_root`, `chain_evidence`, `orphan_amendment`,
`vendor_id`/`vendor_id_source`, `era`, `item_no`/`item_code`,
`unpaired_reason`, `bar_citation`, and every `<field>_source` tag from E3 —
see `link.py`'s and `bar_fill.py`'s docstrings for the complete list if you
need to work below the published sheet.

## 5. How pairing and chaining work

**Intro↔action pairing (F2, `link.py`).** The board usually votes on an item
twice: introduced at one meeting, voted at the next (7–35 days later, modal
gap 14 days). Those are two separate rows in `extracted_filled.jsonl`;
`link.py` folds them into one action row, action-meeting data winning any
field conflict, both citations kept (`citations=[intro, action]`).

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
  one of two overlapping-source families (`ERA_FAMILY`, see §11): `legacy`/
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
- **Final pairing rate: 969/1,165 introductions (83.2%)** (`qa/link_report.md`).
  Multi-vendor members are matched across introduction/action by vendor key
  (not title), so a co-vendor whose amount was revised between the two
  meetings still yields one row (the action meeting wins, `amount_conflict`
  records it).

**Amendment chains (F2, same module).** Groups a `new`/`purchase` root with
its later `amendment`/`change_order`/`renewal`/`final_acceptance` rows into
one `chain_id`, run *after* the multi-vendor explode (§6), so each exploded
member chains on its own.

- `chain_method="id"` — rows share a normalized `contract_id` or `po_number`.
  190 chains / 437 rows.
- `chain_method="vendor_project"` — same vendor **and** either (a) title
  token-Jaccard ≥ 0.60 with ≥2 shared distinctive tokens, or (b) money
  continuity: one row's `prior_total` equals another's `revised_total`/
  `amount` to the cent. 130 chains / 402 rows.
- `chain_method="singleton"` — everything else. 1,139 chains (most
  contracts in this corpus have no amendment on record).
- **Totals: 1,461 chains, 1,976 rows**, size distribution 1→1,139, 2→221,
  3→60, up to one chain of 13. `qa/reconcile_report.md` check 5 confirms
  every chain's `sequence` is contiguous and no action row (including
  `-vN` multi-vendor members) is claimed by more than one chain.
- `orphan_amendment=true` marks an amendment/change_order/renewal/
  final_acceptance row whose chain has no `new`/`purchase` row at or before
  it — common and expected pre-2016 (the parent contract predates the
  corpus).

**Source precedence for competing copies of the same meeting** (`segment.py`'s
`source_rank`, upstream of both pairing and extraction): (1) **official
beats unofficial/draft** — Blackboard published `..._Minutes_UNOFFICIAL.pdf`
drafts alongside the copy WordPress later carried as the record, and the
two paginate differently; (2) **`wp` beats `blackboard` beats `legacy`
beats `archive`** (`ERA_RANK`); (3) amended beats official/approved/final
beats revised/updated beats a plain copy; (4) longest text wins. The
documents a winning copy beat are never discarded — they're recorded on the
winning item's `extractor_notes` as `"alternate copies: <doc_id> (<stem or
era>); ..."` (up to 3 listed).

## 6. Multi-vendor items: one row per vendor

Some motions award several vendors at once — e.g. one RFQ 05790 vote naming
Overlake ($283,000), Fairfax/NWSOIL ($646,000), and Seneca ($961,000) in a
single motion, or a joint award "with X, Y and Z" that prints one shared
not-to-exceed. `extract.py` marks these on the item with a structured
`co_vendors` list (`[{vendor_raw, amount, amount_kind}, ...]`) and, for the
shared-total case, `group_total`; `link.py`'s `explode_multi_vendor`
(Part 1b) fans them out **after pairing, before chaining** so a vendor
analysis sees every awardee as its own row:

- The **primary** row keeps its `action_id`; each co-vendor becomes its own
  row with `action_id = <primary>-v2`, `-v3`, ... — numbered in the order
  the *action* meeting printed the vendors, introduction-only vendors
  appended in vendor-key order, so numbering is stable across reruns.
- Members share the primary's meeting fields, citations, `board_action`,
  `vote`, title, and funding detail, and carry their own `vendor_raw`/
  `vendor_id`/`amount`/`amount_kind`.
- `amount` is **null** on a member whose own figure wasn't printed. The
  shared figure lives in `group_total` on *every* member row (primary
  included) and is **never split, apportioned, or copied into `amount`** —
  summing `amount` over a `multi_vendor_group` never double-counts, but
  summing `group_total` down the column would.
- `CO_VENDOR_BLANKED_FIELDS` clears the primary's `contract_id`/
  `po_number`/`prior_total`/`revised_total` on members: a joint award gives
  each vendor its own contract, so members chain by vendor+project (§5),
  not by the primary's identifiers.
- **55 groups, 140 member rows** (85 extra rows beyond the 55 primaries) —
  e.g. the 6-vendor 2016-06-30 A.7 / 2016-07-06 A.7 pair (special-education
  day-treatment placements: Spring Academy, Yellow Wood Academy, Hamlin
  Robinson, Ryther, Brightmont Academy, Catapult Learning), or the one true
  shared-total group (2019-06-12 A.13, Overlake/Fairfax-NWSOIL/Seneca,
  `group_total=$1,890,000`). Of the 55 groups, only that one prints a
  shared total; every other group's members each have their own `amount`.

The `vendors` sheet counts multi-vendor motions per member — each vendor
named in a joint award contributes its own action row — so every awardee
shows up in vendor rollups; `group_total` is deliberately excluded from
`amount_sum` there.

## 7. Vendor normalization workflow (F1, `vendors.py`)

1. `canonical_key()` folds a raw vendor string automatically: strips
   contract/bid-number award-clause prefixes E1 sometimes swallowed
   ("Contract D5050 to X" → "X"), strips trailing project descriptors,
   casefolds, drops punctuation and legal suffixes (Inc/LLC/Corp/...),
   normalizes common abbreviations, drops a leading "the".
2. `extractors/sps_web/vendor_aliases.csv` (checked into git, hand-maintained,
   507 lines) maps a folded key to a canonical display name and a
   `vendor_class`. 101 of 663 distinct raw vendor strings currently map
   through an alias row; 539 map by exact key alone.
3. Near-duplicate keys the automatic key-fold didn't unify are *proposed*
   in `out_sps_web/contracts/vendors_review.csv`, a **scratch worksheet** —
   nothing below a `ratio ≥ 0.92` string-similarity threshold (or `ratio ≥
   0.85` with identical first two tokens) is even proposed. Marking a row's
   `approve` column `y`/`n` and rerunning `vendors.py` **harvests the
   decision into `extractors/sps_web/vendor_merges.csv`** (the durable,
   git-tracked system of record — key pair, `y`/`n`, the two canonical
   names at decision time, and a note) and the row then disappears from the
   worksheet; the worksheet only ever lists still-undecided proposals. **62
   decisions recorded so far: 34 `y` (merge) / 28 `n` (never propose
   again)** — 0 proposals currently await review. Notable `n` decisions:
   City of Seattle is kept **separate** from its own departments (Parks,
   Parks and Recreation, Education and Early Learning, Office of Arts and
   Culture) and from City Year of Seattle — government parent/child
   entities are deliberately not merged even when the string similarity is
   high. Notable `y` decision: `AmplifyScience` merges into `Amplify` (the
   same company, "Amplify Education" — its product was procured as
   "mCLASS" in 2015 and "Amplify Science" in 2019).
4. `vendor_class` values: `government`, `cooperative`, `contractor`,
   `nonprofit`, `school_placement`, `unknown`, plus `labor_union` (CBAs are
   a large slice of this corpus and are not contractors) and
   `not_a_vendor` (the district itself, project names, bid-number labels,
   and other E1 capture noise — 24 distinct strings). `not_a_vendor` rows
   keep `vendor_id=null` in `vendor_map.jsonl` so downstream code can drop
   them. **99 vendors currently sit in `unknown`** (class mix: contractor
   229, unknown 99, government 27, nonprofit 27, school_placement 26,
   labor_union 5, cooperative 4) — mostly newer strings the alias table
   hasn't classified yet; `vendor_aliases.csv` needs an ongoing pass as the
   corpus grows, not a one-time fix.

To add a new alias or fix a misclassification: edit
`extractors/sps_web/vendor_aliases.csv` directly and rerun `vendors.py`. To
approve or reject a proposed cluster merge: mark `approve` in
`vendors_review.csv` and rerun (it lands in `vendor_merges.csv`
automatically) — or, for a merge you already know is right/wrong, add the
row to `vendor_merges.csv` by hand (its header comments document the
`key_a,key_b,decision,canonical_a,canonical_b,note` format). Either way,
rerun `link.py` and `publish.py` afterward to propagate the new
`vendor_id`/`vendor_class`.

## 8. The BAR detail pass (E3, `bar_fill.py`)

Runs after E2, before F1/F2. **Scope: all years** (`--since 2004-08-01`
default; it was first run for 2016-08-01 forward) — but it can only fill
what exists: the Board Action Report corpus (`kind="bar"` in
`documents_classified.jsonl`) is really only usable from 2016 forward (see
COVERAGE.md table 3), and pre-2016 BARs, where they exist at all, are a
much smaller, less standardized set. It never touches `extracted.jsonl`; it
writes a parallel file, `contracts/extracted_filled.jsonl`, same rows and
row order, with BAR-derived fields merged in — this is the file `vendors.py`
and `link.py` now read.

**Why this pass exists.** Two classes of row the minutes leave blank:

- **Final-acceptance closeouts.** The motion says only "...accept the work
  performed under Contract P5131 with Lincoln Construction, Inc. ... as
  final" — no dollar figure at all. The BAR's fiscal-impact section carries
  the closeout table (`Contract Amount` / `Change Orders` / `WSST` / `Total
  Contract including WSST` / `Project Retention`), which is where the real
  final contract value lives: `Contract Amount → prior_total`, `Total
  Contract including WSST → amount` (`amount_kind="final"`) and
  `revised_total`.
- **New contracts/amendments whose motion defers to the attachment**
  ("...in the amount as attached to the Board Action Report"). The BAR says
  "Fiscal impact to this action will be $X" / "not to exceed $X" / "The
  total contract amount is $X".

**Linking a row to its BAR.** Candidates are every BAR attached to the
row's own meeting or a meeting 0-60 days earlier (same window `link.py`
uses for pairing), tried in 6 tiers (item-code match, first; title Jaccard/
containment/slug; vendor+contract-id last) — the first tier with a
*unique* winner wins; a tie links nothing (`ambiguous`). Only the BAR's
first 6 pages are read (header/title/motion/fiscal-impact are always up
front; the rest of a "packet" PDF is the draft contract itself, full of
boilerplate money that must never be mistaken for the board action's
figure). **1,138 of 1,232 in-scope rows linked to a BAR (92.4%)**, almost
entirely via `item_code_exact` (709) and `title_jaccard` (409).

**Merge is conservative — a field fills only when null on the row; a
minutes-derived value is never overwritten.** A filled amount must parse,
be ≥ $1,000 (below the board-approval threshold — a smaller figure is
almost always a unit price or page number) and ≤ $2B, and its digits must
be printed in the BAR text; amounts are read only from a **labelled**
position (the closeout table, "Fiscal impact ... will be", "not to exceed",
"total contract amount", "in the amount of") — there is deliberately no
bare `$X` pattern. **250 amounts filled by the regex pass** (of which the
bulk are `final_acceptance` closeouts — 210 of 241 in-scope final
acceptances gained an amount this way), plus **fund** (745 rows),
**funding_source_text** (624), **procurement_method** (518),
**revised_total**/**prior_total** (217/216), **vendor_raw** (82, only when
the minutes left it null, and only a string verbatim in the BAR text — the
BAR's own co-vendor reading is kept separately, unmerged, in
`vendor_raw_bar`/`co_vendors_raw_bar`), **term_start/term_end** (56/56),
**contract_id** (21), **po_number** (9), **department** (2, only from a
literal "Department:" line — a BAR's "LEAD STAFF: ..., Chief Operations
Officer" role is kept separately as `bar_lead_staff`, never merged into
`department`, since this corpus's `department` values are board-committee
codes like "Ops"/"C&I").

**Where the BAR and the minutes disagree**, the row's amount is left alone
(minutes always win) and `bar_amount_conflict:<bar>!=<row>` is appended to
`extractor_notes` — **91 conflicts logged** (`qa/bar_conflicts.jsonl`, full
list with excerpts, kept for the E1 owner to triage). Several are E1 bugs,
not BAR-parsing bugs — a motion that quotes only the GC/CM
pre-construction fee rather than the GMP (see §11's extractor-fix list), or
the $250,000 board-approval threshold being echoed as if it were the
contract amount. Conflicts ≥100× apart are treated as `bar_amount_implausible_vs_minutes`
and `prior_total`/`revised_total` are also withheld from that BAR, since at
that distance one side is a bad parse.

**LLM fallback (`--merge-llm`), for rows the regex still left with no
amount and a linked BAR.** 132 rows batched, 131 LLM rows read back, **52
rows gained ≥1 field** (fund 22, term_start 16, amount/amount_kind 15 each,
funding_source_text 10, department 6, term_end 5, po_number 5, contract_id
2). Every LLM row is validated against **that row's own `bar_text`** — the
only text the model saw — with hard rejects (an amount that doesn't parse,
is under $1,000/over $2B, or isn't printed in the text; any identifier
absent from everything the model was shown) and soft field-drops (a `fund`
outside the vocabulary, an unparseable date) logged separately. Beyond that
validator, a **hand-checked amount reject list**
(`extractors/sps_web/bar_llm_amount_rejects.csv`, git-tracked, keyed by
`(meeting_id, item_no, char_start)`) blocks `amount`/`amount_kind` for
individual rows a human reviewed against the BAR and judged wrong or
partial — the first row of a multi-vendor table, a base salary where the
contract is total compensation, the top of a stated range, one school year
of two — **6 amounts blocked** this way even though the model's figure
passed every automated check; every other field the model supplied for
those rows is still merged, tagged `extractor_notes:
bar_llm_amount_rejected:<reason>`. Filled fields carry `<field>_source =
"bar_llm"` (or `"bar"` for the regex pass, `"minutes"` when the row already
had the value) so `publish.py` can emit `amount_source` without
re-deriving it.

**Order matters and makes the pair idempotent**: a plain `bar_fill` run
always rebuilds `extracted_filled.jsonl` from `extracted.jsonl` from
scratch, dropping any LLM fills — always rerun `--merge-llm` after it.
`--merge-llm` only ever writes null fields, so running it twice changes
nothing the second time.

**A spot-check this session** (not yet a standing QA report) hand-verified
40 rows since 2016-08-01 against their linked BAR: 28 of 30 checked fields
matched exactly, and the other 2 were confirmed correct against a
different part of the same citation than the one initially flagged.

**Since 2016-08-01 (891 action rows), the combined effect: 756 rows have an
amount** (566 from the minutes, 179 from the BAR regex pass, 11 from the
BAR LLM fallback), **769 have a vendor**, **694 have both**. The 135
remaining amount-less rows are mostly genuinely non-contract `other`-type
items admitted by the pre-filter (CBAs, the superintendent's own contract,
fee-schedule changes) and a residue of final acceptances whose BAR has no
closeout table to read. See COVERAGE.md's "Last 10 years" table.

## 9. Extraction design: regex-first, LLM for the residual (E1/E2)

**Pre-filter (E1).** Every segmented business item is tested against an
`INCLUDE_RE` (contract/agreement/amendment/bid/lease/RFP/etc.) and a set of
named `EXCLUDE_RES` (warrants, minutes-of-minutes, personnel reports, board
policy/resolution titles, revenue acceptance, bargaining, calendar
amendments) — exclusions run first and are hard vetoes even when an
include keyword also matches. 44.4% of all 6,452 segmented items are
admitted (2,862); a hand-audited 60-item sample (30 admitted + 30 rejected)
scored 100%/100% precision.

**Regex extraction (E1).** ~20 named vendor-anchor patterns and ~15 named
amount patterns walk each item's own text — never the whole document —
filling `vendor_raw`/`amount`/`amount_kind`/`action_type`/identifiers/terms.
**Never guesses**: a field the text does not literally print stays `null`.
When an item names more than one vendor or amount, the first-anchored pair
is kept as primary; a *structured* multi-vendor case becomes `co_vendors`
(§6) instead of being discarded. Regex coverage (vendor + amount-or-no-
dollar-figure + non-`other` action type, validator passing) is **67.7%
overall (1,939/2,862)**, by format family: modern 83.0%, wp1620 72.7%,
blackboard 64.3%, legacy 59.8%, archive 57.6%; 76.0% for post-2016 items
combined (target was ≥70%).

**Validator (`extract.validate()`)**, applied to every row regardless of
which pass produced it: amounts parse, are non-negative, and ≤
`AMOUNT_CEILING` ($2B — the source really does print typos like
"$39,542,000,000" for student transportation); `action_type`/`amount_kind`
are in the fixed vocabulary; an `amount` requires a non-null `amount_kind`;
for `amendment`/`change_order` rows, `revised_total ≥ amount`;
`vendor_raw`, every `co_vendors` entry, and every `contract_id`/
`po_number`/`bid_number`/`rfp_number` must appear **verbatim in this
item's own text**; citation page bounds are sane; `action_type` has
textual support; a row with no `amount` is flagged if the item text has a
`$` figure anywhere (`amount_missing_though_text_has_money`) — the signal
that routes an item to the LLM residual pass. **One deliberate exception**:
an LLM row is allowed a null `amount` without tripping this check when its
`extractor_notes` explains why — `malformed_amount:` (the source's own
printed figure is corrupted, e.g. column-bleed OCR) or `not_a_contract:`
(E1's regex admitted the item but it isn't actually a contract action).

**Residual / LLM pass (E2).** Items failing the regex fill or the validator
go to `contracts/residual.jsonl` (**923 items**), batched ~100/file, run
in-session (no API key — one subagent per batch, `haiku` first, escalate to
`sonnet` on validator failure). **`e2_merge.py` is idempotent across
rounds**: before touching a key's row in the current batch, it checks
whether `llm_rows.jsonl` already has that key settled at this round or a
later one, and if so leaves it completely alone. Outcome: **915 of 923
residual items resolved by the LLM pass, 8 in `manual_review.jsonl`**.
Combined regex+LLM coverage by era: legacy 99.7%, archive 99.8%, blackboard
99.8%, wp1620 99.8%, modern 100.0% (`qa/e2_report.md` — "coverage" means
*some* row exists for the item, not that every field is filled).

**Gold set.** **104 hand-labelled items** (`tests/fixtures/gold/gold.jsonl`),
resolved against the corpus by `(meeting_id, item_no)` — `char_start` is
advisory only, used to disambiguate the 26 `(meeting_id, item_no)` pairs
that genuinely recur, since re-running the segmenter shifts offsets
whenever pagination or the chosen source document changes. Scores:
**admitted 100%/100%, vendor_raw 100% precision / 96.2% recall (3 real
misses, no false vendors), amount 100%/100%, amount_kind 100%/100%,
action_type 100%/100%, revised_total 100%/100%, prior_total 100%/100%,
contract_id 100%/100%, co_vendor_count 100%/100%, group_total 100%/100%.**

## 10. Extractor-fix gotchas worth knowing before you read a raw amount

A handful of pattern fixes materially change what "the amount" means for a
row — know these before trusting a raw number:

- **GC/CM (general contractor/construction manager) awards use the GMP, not
  the pre-construction allowance.** A GC/CM item authorizes a small
  pre-construction services fee *and* a Guaranteed Maximum Price for the
  whole job in the same motion; taking the first not-to-exceed figure
  (the pre-construction fee) understated 14 rows by 76×-587× before the
  `a_gmp` pattern was added to prefer the GMP figure specifically.
- **"$X annually, or $Y over the term" → Y**, not X — the `a_term_total`
  pattern picks the multi-year total, not the annual rate, when both are
  printed together.
- **`monthly` is its own `amount_kind`** (`a_monthly` pattern, "$X a/per/each
  month") — distinct from `annual`; don't conflate the two when aggregating.
- **Curriculum/instructional-materials adoptions take the product or
  publisher as the vendor**, not the school subject or course — e.g.
  "purchase AmplifyScience as the core instructional materials" →
  `AmplifyScience`; confirmed examples in this corpus: AmplifyScience,
  Carbon TIME, Inquiry By Design, Imagine Learning, McGraw Hill. A trailing
  "... Middle School Curriculum"/"Instructional Materials"/"Program" tail is
  trimmed from the captured name (`trim_adoption_tail`).
- **Course names, project names, generic-only names, and leading articles
  are rejected as vendors**, not captured — "Roosevelt High School Science
  Modernization", "Construction Group" (no proper noun survived), a bare
  "the", district-produced things ("district-developed curriculum",
  "in-house", subject-code fragments like "Chem A") never become
  `vendor_raw`.
- **Compound names are never split at "and"** — "Parks and Recreation
  [Department]", "Listen and Talk" stay whole; the joint-vendor splitter
  only fires when the right-hand side of "and" clearly opens a *new* legal
  name (see `split_joint_vendors`'s docstring for the exact heuristic).

## 11. Format families / era gotchas (from `segment.py`/`extract.py`)

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
  unanimously."), so no separate parser was needed. Item codes (C01/SC01/
  A01/I01) come from sibling BAR filenames, not the agenda/minutes text.
- **`meeting_id` is the meeting where the item's *outcome* was recorded (the
  action meeting for a paired row), not the subject the document is about.**
  WP-era minutes filenames are `C01_<posting meeting>_Minutes_<meeting the
  minutes describe>` — the manifest's naive `meeting_id` is the posting
  meeting; `segment.py` re-derives the true subject date (`subject_date`)
  before assigning items to a meeting.
- **BAR filename dates are the introduction date, not the action date.** A
  Board Action Report keeps the item code of the meeting where the item was
  *introduced* even when it's re-linked at the later action meeting — this
  is exactly why `bar_fill.py`'s linker searches a 0-60 day window rather
  than the row's own meeting alone. `section` on a segmented item always
  comes from the document's own subsection heading, never from the
  filename's item-code letter.
- **Consent items removed and re-voted appear once, not twice.** An item
  pulled from consent and re-voted under "Items Removed from the Consent
  Agenda" is emitted only from that removed-section appearance; the
  original consent-agenda copy is suppressed so Phase E can't double-count
  it. An item removed with *no* re-vote keeps `board_action="removed"`.
- **The 2007-11 minutes hole.** 2007-08 through 2010-11 have agendas for
  nearly every meeting but very few real minutes — see COVERAGE.md.
  Agendas record no `board_action` or `vote`, so most rows from those years
  carry `board_action="introduced"` or `unknown` even for items that
  plainly passed.
- **Legacy/archive/blackboard agendas rarely carry a dollar figure at
  all** — the vendor and the amount usually live only in the (often
  thinner) minutes or in a Board Action Report that E3's scope (2016+
  only) doesn't reach for these eras.
- **Legacy PDFs sometimes carry a wrong date in the page header** — a
  filename `010908agenda.pdf` was seen to print "January 9, **2007**" on the
  page itself. The *filename* date wins for meeting assignment in this era.
- **Blackboard also published draft copies.** `..._Minutes_UNOFFICIAL.pdf`
  drafts exist alongside the official copy WordPress later carried, and the
  two paginate differently — `source_rank` always prefers the official
  copy (§5).
- **Phrasing shifts across eras**: 2005-06 minutes/agendas file introduction
  items under a roman "New Business" heading enumerated **A., B., C.** (not
  1., 2., 3.); modern minutes' outcome sentence is "This motion was
  approved unanimously (Directors ... voted yes)" where 2016-2021 says
  "This motion passed with a vote of 5-0-1 (...)" and legacy says the terse
  "This item passed unanimously."; committee annotations like "(Ops,
  September 5, for Approval)" appear between title and description only in
  the 2016-17 → 2020-21 window.

## 12. Reconciliation (H2) — what's been verified

`extractors/sps_web/reconcile.py` runs 7 automated checks with no human
sampling; all pass except one WARN (`qa/reconcile_report.md`):

1. **Meeting coverage (WARN)** — 26/1,023 meetings (2.5%) have fetched,
   classified documents but none of them is agenda/minutes kind. Real,
   permanent gaps — see COVERAGE.md.
2. **Citation resolution — PASS.** All citations resolve, pages in bounds,
   URLs well-formed; a live HTTP sample all returned 200.
3. **Money sanity — PASS.** No negative or > $2B amounts, no
   `amendment`/`change_order` row with `revised_total < amount`, no
   `amount` without an `amount_kind`; of the rows carrying `prior_total` +
   `amount` + `revised_total` all at once, 0 mismatches on
   `prior_total + amount == revised_total`.
4. **Vendor mapping — PASS.** All 1,490 `vendor_raw` values on action rows
   map to a known `vendor_id` or are flagged `not_a_vendor`.
5. **Pairing/chains — PASS.** 1,461 chains, every `sequence` contiguous, no
   action row claimed by more than one chain (co-vendor `-vN` ids included,
   each resolving to a real primary row), no paired row where the
   introduction is dated after the action.
6. **Time series — PASS.** No school year's action-row or admitted-item
   count drops more than 50% versus both neighboring years.
7. **Key uniqueness — PASS.** `action_id` is unique across all 1,976 rows;
   `(meeting_id, item_no, char_start)` is unique across all 6,452 items.

## 13. Known limitations

- **Naive amount sums double-count.** `amount` mixes not-to-exceed, revised-
  total, increase, and final values, and, before F2 pairing, an
  introduction and its action are two separate rows with (often) the same
  amount printed twice. `vendors` sheet's `amount_sum` is explicitly a
  sort key, not a spend figure. Use `chain_total_latest` for "what is this
  contract worth now," and even that is "last reported total on the record,"
  not audited lifetime spend.
- **`group_total` (§6) must never be summed down the column** — it's the
  same shared figure repeated on every member of a multi-vendor group.
- **8 rows in `manual_review.jsonl`** failed extraction after regex + 2 LLM
  rounds and need a human to read the source page directly.
- **26 meetings have documents but no usable agenda/minutes text**
  (reconcile check 1) — a permanent structural gap.
- **E3 (BAR detail pass) covers all years but only 2015-16 onward has BARs to read**; before that the pass was
  request — `fund`/`funding_source_text`/`procurement_method`/`term`/
  `contract_id` remain sparse before that date, filled only where the
  item-text regex/LLM pass happened to pick them up incidentally.
- **91 BAR-vs-minutes amount conflicts are logged, not resolved**
  (`qa/bar_conflicts.jsonl`) — the minutes value is always kept, but some
  of these are known E1 extraction bugs (GC/CM allowance vs. GMP, the
  $250,000 threshold echoed as an amount) still worth a look.
- **Pre-2004-05 is offline-only.** WA State Digital Archives title 551 is
  not online yet; anything earlier requires a manual request to SPS
  Archives (archives@seattleschools.org, 206-252-0796).
- **committee packets (1,333 Wayback rows) are set aside**, not merged into
  the meeting/document inventory — an open owner decision (PLAN.md §4).
- **99 vendors are unclassified** (`vendor_class="unknown"`) — `unknown` is
  not zero and needs an ongoing pass on `vendor_aliases.csv`, not a
  one-time fix, as the corpus grows.
- **BigQuery has not been loaded** — the owner's call; `--bq` is a flag
  away once ready (§1, §2).

## 14. Anti-patterns

- **Don't `SUM(amount)` across a chain (or across a vendor) expecting a
  spend total.** It double-counts: an amendment's `amount` is the
  *increase*, not the new total, and `revised_total` on the same row is
  already the cumulative figure. Use `chain_total_latest`, and even that is
  "last reported total on the record," not audited lifetime spend.
- **Don't sum `group_total` across a `multi_vendor_group`.** It's the same
  shared figure copied onto every member row — count it once per group.
- **Don't treat `revised_total` as an increment.** It is the *cumulative*
  contract value after the action, by construction. Subtract `prior_total`
  from `revised_total` if you want the increment, and only when both are
  non-null on the *same* row.
- **Don't join on `(meeting_id, item_no)` alone** — pairs recur across
  combined-meeting PDFs and same-meeting retaken items; join on
  `(meeting_id, item_no, char_start)` if you need to hit `extracted.jsonl`,
  or just use `action_id` on the published `actions` sheet, which is
  already unique (reconcile check 7).
- **Don't assume a null `board_action`/`vote` means the item failed.** Most
  agenda-sourced pre-2016 rows are `board_action="unknown"` or
  `"introduced"` simply because the agenda is a pre-meeting document that
  never records an outcome — see §11.
- **Don't assume a null `amount` means no dollar figure was printed
  anywhere.** Check `amount_source` and `extractor_notes` first — a row can
  be null because a BAR figure was rejected (`bar_llm_amount_rejected:`) or
  a printed figure was malformed (`malformed_amount:`), not because nothing
  was there.
- **Don't trust `kind_guess` in the manifest as a document classification.**
  It's A1/A2's cheap filename/link-text guess; `classify.py`'s `kind` is
  the authority — always use `kind`, not `kind_guess`, downstream of Phase C.
- **Don't merge two vendor strings just because they look similar.** Only
  `vendor_aliases.csv` rows and `vendor_merges.csv` `y` decisions are ever
  merged; a Jaccard/ratio similarity alone is a *proposal*, not a merge —
  and government parent/child entities are deliberately kept separate even
  at high similarity (§7).

## See also

[`extractors/sps_web/COVERAGE.md`](../../extractors/sps_web/COVERAGE.md) —
per-school-year meeting/document/item/row counts and what's missing and why.
[`extractors/sps_web/PLAN.md`](../../extractors/sps_web/PLAN.md) — the
full pipeline design, source map, and task cards this guide summarizes.
[`out_sps_web/publish/README.md`](../../out_sps_web/publish/README.md) —
generated: current row counts, action-type/vendor dollar totals, full
column dictionary.
