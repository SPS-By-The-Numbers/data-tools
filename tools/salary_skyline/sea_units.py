"""Unit definitions for the central-office redistribution game (admin_game).

Two lists, both keyed on OSPI duty ROOT codes (same convention as
salary_bands.py — see docs/guides/S275_SALARY_SKYLINE.md §3):

  CUTTABLE   — the components a player may count as "Central Administration".
               Each becomes one bubble cluster on the game board.
  RECIPIENTS — the SEA-represented sub-groups the removed payroll is
               distributed to.  Membership is APPROXIMATED from duty codes;
               real bargaining-unit rosters differ at the margins.

The two sets are disjoint by construction so a cut position can never also be
a recipient.  Crafts/custodial/service roots (92, 93, 95, 97, 98) belong to
other unions (e.g. Local 609/IUOE) and appear in neither list.
"""

# key, label, duty-code caption, duty roots, cuttable-by-default
CUTTABLE = [
    ("dist",   "District administration",             "11–13",  (11, 12, 13),         True),
    ("dirsup", "Classified directors & supervisors",  "99",          (99,),                True),
    ("prof",   "Classified professional staff",       "96",          (96,),                True),
    ("school", "School administration",               "21–25",  (21, 22, 23, 24, 25), False),
]

# key, label, duty roots, chip color family (matches salary_bands GROUPS)
RECIPIENTS = [
    ("teach",  "Teachers",                    (31, 32, 33, 34), "B"),
    ("subs",   "Substitute teachers",         (52,),            "B"),
    ("cert",   "Certificated support",        (39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 63, 64), "C"),
    ("para",   "Paraeducators & aides",       (91,),            "D"),
    ("office", "Office & clerical (SAEOP)",   (94,),            "D"),
]
