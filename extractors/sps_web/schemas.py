"""Schema-dict definitions for the board-contracts spreadsheet/BigQuery
publish step (task G1; see ``extractors/sps_web/PLAN.md``).

Same shape as the SAFS schema modules (``extractors/safs/schemas/*.py``,
see CLAUDE.md "Schema system"): a plain dict with ``name``, ``doc``,
``fields`` (each ``name``/``field_type``/``doc``, plus ``is_logical_key``
where there is a natural key), and ``unique``. ``field_type`` is one of the
types ``extractors/safs/avro_schema.py`` knows how to convert: ``decimal``
(BigQuery NUMERIC(38,9)), ``string``, ``int``, ``boolean``, ``timestamp``.

Unlike the SAFS schemas, these are not read by ``from_raw_file``/``orm.py``
-- there is no Postgres staging step for this pipeline (see
``extractors/sps_web/publish.py``'s docstring) -- so fields have no
``source``/``extractor`` keys, only the AVRO-relevant ones. ``publish.py``
builds rows already shaped to these field names and hands them straight to
``avro_schema.to_avro_schema``/``to_avro_value``.

AVRO (and this dict shape) has no array/record field type, so the source
``citations`` list (``out_sps_web/contracts/contract_actions.jsonl``, at
most 2 entries per row -- see ``link.py``) is flattened here into
``citation_1_*``/``citation_2_*`` columns, matching the spreadsheet's
``actions`` sheet. The full nested ``citations`` array is preserved only in
``contracts.jsonl`` (not loaded to BigQuery).
"""

CONTRACT_ACTIONS_SCHEMA = {
    "name": "contract_actions",
    "doc": ("One row per SPS board action (an introduction and its later "
            "vote are folded into one row where matched -- see link.py), "
            "with contract-chain linkage and citations to primary-source "
            "PDF pages. Built by extractors/sps_web/publish.py from "
            "out_sps_web/contracts/contract_actions.jsonl."),
    "fields": [
        {"name": "action_id", "field_type": "string", "is_logical_key": True,
         "doc": ("Unique id for one board action row (`<meeting_id>-<item_no>-<hash>`). "
                 "A motion awarding several vendors becomes one row per vendor: the "
                 "primary keeps this id and the co-vendors get `-v2`, `-v3`, ... "
                 "suffixes (see multi_vendor_group).")},
        {"name": "chain_id", "field_type": "string",
         "doc": "Id grouping this action with its contract's other amendments/change orders/renewals over time."},
        {"name": "sequence", "field_type": "int",
         "doc": "0-based position of this action within its chain, ordered by meeting date."},
        {"name": "chain_method", "field_type": "string",
         "doc": "How the chain was formed: contract_id | po_number | vendor_project | singleton | ..."},
        {"name": "chain_size", "field_type": "int",
         "doc": "Number of actions in this action's chain."},
        {"name": "chain_total_latest", "field_type": "decimal",
         "doc": ("Most recent revised_total/amount known for this chain as of this "
                 "action. Naive -- see the vendors table's amount_sum note.")},
        {"name": "is_root", "field_type": "boolean",
         "doc": "True if this is the first (new-contract) action in its chain."},
        {"name": "orphan_amendment", "field_type": "boolean",
         "doc": "True if this looks like an amendment/change order with no earlier root action found in the corpus."},
        {"name": "meeting_id", "field_type": "string",
         "doc": "Meeting at which the vote (or, for immediate items, the sole appearance) took place."},
        {"name": "meeting_date", "field_type": "timestamp", "doc": "Date of that meeting."},
        {"name": "school_year", "field_type": "string", "doc": "School year of the meeting, e.g. 2004-05."},
        {"name": "item_no", "field_type": "string", "doc": "Board agenda item number for the action."},
        {"name": "item_code", "field_type": "string", "doc": "District's item code, when present."},
        {"name": "section", "field_type": "string",
         "doc": "Agenda section the action row came from (consent, action, immediate, other)."},
        {"name": "era", "field_type": "string",
         "doc": "Which site generation/archive the source document came from (legacy, archive, wp1620, modern)."},
        {"name": "board_action", "field_type": "string",
         "doc": "introduced | approved | removed | withdrawn | unknown, from the minutes/agenda text."},
        {"name": "vote", "field_type": "string", "doc": "Vote tally/description, when recorded."},
        {"name": "immediate_action", "field_type": "boolean",
         "doc": "True if the board took immediate action at a single meeting rather than introduce-then-vote."},
        {"name": "title", "field_type": "string", "doc": "Board agenda item title."},
        {"name": "vendor_raw", "field_type": "string", "doc": "Vendor name exactly as it appeared in the source text."},
        {"name": "vendor_name", "field_type": "string", "doc": "Vendor name as extracted (pre-canonicalization)."},
        {"name": "vendor_id", "field_type": "string",
         "doc": "Canonical vendor id (join key to the vendors table), or null if no vendor was identified/normalized."},
        {"name": "vendor_id_source", "field_type": "string",
         "doc": "How vendor_id was assigned: map | fallback | none."},
        {"name": "vendor_canonical", "field_type": "string", "doc": "Canonical vendor display name."},
        {"name": "vendor_class", "field_type": "string",
         "doc": ("Vendor category, joined from the vendors table: contractor, government, "
                 "nonprofit, cooperative, school_placement, labor_union, unknown, not_a_vendor. "
                 "Null if vendor_id is null.")},
        {"name": "action_type", "field_type": "string",
         "doc": "new | amendment | change_order | final_acceptance | renewal | other, per the extractor's classification."},
        {"name": "amount", "field_type": "decimal",
         "doc": ("Dollar amount named in this action (not-to-exceed, revised total, or "
                 "increase, per amount_kind). Naive -- see the vendors table's note.")},
        {"name": "amount_kind", "field_type": "string",
         "doc": "What `amount` represents: not_to_exceed | revised_total | increase | unspecified | ..."},
        {"name": "prior_total", "field_type": "decimal", "doc": "Contract total before this action, when stated."},
        {"name": "revised_total", "field_type": "decimal", "doc": "Contract total after this action, when stated."},
        {"name": "contract_id", "field_type": "string", "doc": "District contract/PO identifier, when captured."},
        {"name": "po_number", "field_type": "string", "doc": "Purchase order number, when captured."},
        {"name": "term_start", "field_type": "timestamp", "doc": "Contract term start date, when captured."},
        {"name": "term_end", "field_type": "timestamp", "doc": "Contract term end date, when captured."},
        {"name": "department", "field_type": "string", "doc": "Sponsoring district department, when captured."},
        {"name": "program_or_project", "field_type": "string", "doc": "Program or project name/number, when captured."},
        {"name": "fund", "field_type": "string", "doc": "Funding fund, when captured."},
        {"name": "funding_source_text", "field_type": "string", "doc": "Free-text funding source description, when captured."},
        {"name": "procurement_method", "field_type": "string",
         "doc": "Procurement method (RFP, sole source, cooperative purchasing, etc.), when captured."},
        {"name": "extractor", "field_type": "string", "doc": "Which extractor produced this row: regex | llm."},
        {"name": "paired", "field_type": "boolean",
         "doc": "True if an introduction row was matched and merged into this action row."},
        {"name": "pair_method", "field_type": "string",
         "doc": "Match tier that produced the introduction/action pairing (see link.py); null if unpaired."},
        {"name": "intro_meeting_id", "field_type": "string", "doc": "Paired introduction row's meeting, when paired."},
        {"name": "intro_meeting_date", "field_type": "timestamp", "doc": "Paired introduction row's meeting date, when paired."},
        {"name": "intro_item_no", "field_type": "string", "doc": "Paired introduction row's item number, when paired."},
        {"name": "intro_era", "field_type": "string", "doc": "Paired introduction row's era, when paired."},
        {"name": "intro_extractor", "field_type": "string", "doc": "Paired introduction row's extractor, when paired."},
        {"name": "amount_conflict", "field_type": "boolean",
         "doc": "True if the introduction and action rows disagreed on amount (kept, not vetoed)."},
        {"name": "unpaired_reason", "field_type": "string",
         "doc": "Why an introduction/action row was left unpaired, when applicable."},
        {"name": "llm_confidence", "field_type": "decimal",
         "doc": "LLM extractor's self-reported confidence (0-1), when extractor=llm."},
        {"name": "extractor_notes", "field_type": "string",
         "doc": "Free-text notes from the extractor (e.g. additional amounts seen but not captured)."},
        {"name": "chain_evidence", "field_type": "string",
         "doc": ("Comma-joined tags explaining how this action was linked into its chain "
                 "(e.g. project_tokens), when not linked by contract_id/po_number.")},
        {"name": "citation_1_doc_id", "field_type": "string", "doc": "doc_id of the first citation."},
        {"name": "citation_1_url", "field_type": "string",
         "doc": "Primary-source URL for the first citation, with a #page=N fragment."},
        {"name": "citation_1_page", "field_type": "int", "doc": "Cited page number (page_start) of the first citation."},
        {"name": "citation_2_doc_id", "field_type": "string", "doc": "doc_id of the second citation, when present."},
        {"name": "citation_2_url", "field_type": "string",
         "doc": "Primary-source URL for the second citation, with a #page=N fragment, when present."},
        {"name": "citation_2_page", "field_type": "int", "doc": "Cited page number (page_start) of the second citation, when present."},
        {"name": "citation_3_doc_id", "field_type": "string",
         "doc": "doc_id of the Board Action Report citation (role=bar), when bar_fill.py linked one."},
        {"name": "citation_3_url", "field_type": "string",
         "doc": ("Primary-source URL for the Board Action Report citation, with a #page=N "
                 "fragment, when present.")},
        {"name": "citation_3_page", "field_type": "int",
         "doc": "Cited page number (page_start) of the Board Action Report citation, when present."},
        {"name": "amount_source", "field_type": "string",
         "doc": ("Where `amount` came from: 'minutes' (the item's own motion text) or "
                 "'bar' (filled from the linked Board Action Report by bar_fill.py). "
                 "Null when amount is null.")},
        {"name": "multi_vendor_group", "field_type": "string",
         "doc": ("For a motion that awarded several vendors at once, the primary row's "
                 "action_id, set on every member row (the primary included). Null on "
                 "ordinary single-vendor rows.")},
        {"name": "multi_vendor_n", "field_type": "int",
         "doc": ("Number of vendor rows this multi-vendor motion was split into. Null on "
                 "ordinary single-vendor rows.")},
        {"name": "group_total", "field_type": "decimal",
         "doc": ("Shared not-to-exceed printed for a joint award, repeated on every member "
                 "row of the group. It is NOT split across members and is never copied "
                 "into `amount`, so do not sum it across a group -- take it once per "
                 "multi_vendor_group. Null when each vendor's own amount was printed.")},
    ],
    "unique": [["action_id"]],
}


VENDORS_SCHEMA = {
    "name": "vendors",
    "doc": ("One row per canonical vendor per school year (action count + "
            "naive amount sum), plus one 'ALL YEARS' total row per vendor. "
            "Built by publish.py from contract_actions joined to "
            "out_sps_web/contracts/vendors.jsonl."),
    "fields": [
        {"name": "vendor_id", "field_type": "string", "is_logical_key": True,
         "doc": "Canonical vendor id (extractors/sps_web/vendors.py)."},
        {"name": "vendor_canonical", "field_type": "string", "doc": "Canonical vendor display name."},
        {"name": "vendor_class", "field_type": "string",
         "doc": "contractor | government | nonprofit | cooperative | school_placement | labor_union | unknown."},
        {"name": "school_year", "field_type": "string", "is_logical_key": True,
         "doc": "School year, or 'ALL YEARS' for the vendor's all-time total row."},
        {"name": "n_actions", "field_type": "int", "doc": "Number of board actions for this vendor in this school year."},
        {"name": "n_amounts", "field_type": "int",
         "doc": "Number of those actions with a non-null amount (denominator for amount_sum's coverage)."},
        {"name": "amount_sum", "field_type": "decimal",
         "doc": ("Naive sum of `amount` over this vendor's actions in this school year; mixes "
                 "not_to_exceed/revised_total/increase and, for any introduction/action pair "
                 "link.py could not merge, double-counts. A sort key, not a spend figure.")},
    ],
    "unique": [["vendor_id", "school_year"]],
}


DOCUMENTS_SCHEMA = {
    "name": "documents",
    "doc": ("One row per document cited by at least one board action, with "
            "its classified kind, source meeting, primary-source URL, page "
            "count, and content hash. Built by publish.py from "
            "out_sps_web/manifest/documents_classified.jsonl + "
            "manifest/meetings.jsonl + raw/*/*/*.prov.json, filtered to "
            "doc_ids cited from contract_actions."),
    "fields": [
        {"name": "doc_id", "field_type": "string", "is_logical_key": True, "doc": "Document id."},
        {"name": "kind", "field_type": "string",
         "doc": ("agenda | minutes | bar | warrants | personnel | presentation | packet | "
                 "policy | resolution | image | video | other; null if not yet classified.")},
        {"name": "meeting_id", "field_type": "string", "doc": "Meeting this document belongs to."},
        {"name": "meeting_date", "field_type": "timestamp", "doc": "That meeting's date."},
        {"name": "meeting_title", "field_type": "string", "doc": "That meeting's title, from manifest/meetings.jsonl."},
        {"name": "school_year", "field_type": "string", "doc": "School year of the meeting."},
        {"name": "url", "field_type": "string",
         "doc": ("Primary-source URL: the live seattleschools.org/SharePoint URL when the "
                 "document was fetched that way, else the Wayback id_ URL.")},
        {"name": "pages", "field_type": "int",
         "doc": "Page count from text extraction (totext.py); null if not yet extracted."},
        {"name": "sha256", "field_type": "string",
         "doc": "SHA-256 of the fetched raw bytes, from fetch.py's .prov.json; null if not yet fetched."},
        {"name": "n_citing_actions", "field_type": "int",
         "doc": "Number of board actions in contract_actions that cite this document."},
    ],
    "unique": [["doc_id"]],
}


ALL_SCHEMAS = [CONTRACT_ACTIONS_SCHEMA, VENDORS_SCHEMA, DOCUMENTS_SCHEMA]
