"""Shared duty-band definition for the SPS S-275 salary charts.

Two levels:
  GROUPS  — the color carriers, in plot order (left→right wide, top→bottom tall)
  BANDS   — duty-title bands inside each group, also in plot order

Bands are derived from the OSPI duty ROOT code, not from the `is_classified`
flag. Three classified roots sit in the central-office group rather than with
the rest of the classified series, because the work is administrative or
professional rather than support:

  99  Director or Supervisor  ->  Central administration + central office staff
  96  Professional            ->  Central administration + central office staff

Administration keeps one hue (blue) across both of its groups, stepped down the
documented sequential blue ramp so central office reads darker than school
administration.
"""

# (key, label, short label for legends)
GROUPS = [
    ("A1", "Central administration + central office staff", "Central admin & central office"),
    ("A2", "School administration",                         "School administration"),
    ("B",  "Teachers",                                      "Teachers"),
    ("C",  "Certificated support",                          "Certificated support"),
    ("D",  "Classified support",                            "Classified support"),
    ("E",  "Other",                                         "Other"),
]

# (label, group key, duty-code caption, duty roots)
BANDS = [
    ("District administration",                 "A1", "11–13",         (11, 12, 13)),
    ("Classified directors & supervisors",      "A1", "99",            (99,)),
    ("Classified professional",                 "A1", "96",            (96,)),
    ("Principals & school administration",      "A2", "21–25",         (21, 22, 23, 24, 25)),
    ("Teachers",                                "B",  "31–34",         (31, 32, 33, 34)),
    ("Substitute teachers",                     "B",  "52",            (52,)),
    ("Counselors & social workers",             "C",  "42, 44, 49",    (42, 44, 49)),
    ("Health & therapy services",               "C",  "39, 43, 45–48", (39, 43, 45, 46, 47, 48)),
    ("Librarians & other certificated support", "C",  "40–41, 63–64",  (40, 41, 63, 64)),
    ("Classified technical",                    "D",  "98",            (98,)),
    ("Office & clerical",                       "D",  "94",            (94,)),
    ("Paraeducators & aides",                   "D",  "91",            (91,)),
    ("Crafts, trades & operators",              "D",  "92–93, 95",     (92, 93, 95)),
    ("Service workers",                         "D",  "97",            (97,)),
    ("Extracurricular & leave",                 "E",  "51, 61, 90",    (51, 61, 90)),
]

# Light / dark step per group. A1 and A2 are two steps of the one blue ramp.
COLORS = {
    "A1": ("#184f95", "#86b6ef"),
    "A2": ("#2a78d6", "#3987e5"),
    "B":  ("#eb6834", "#d95926"),
    "C":  ("#1baf7a", "#199e70"),
    "D":  ("#eda100", "#c98500"),
    "E":  ("#9a9a90", "#83837a"),
}

DUTY_TO_BAND = {d: i for i, (_, _, _, roots) in enumerate(BANDS) for d in roots}
OTHER_BAND = len(BANDS) - 1


def band_of(duty_root: int) -> int:
    """Index into BANDS; unlisted roots fall into the trailing catch-all."""
    return DUTY_TO_BAND.get(duty_root, OTHER_BAND)


def bands_of_group(key):
    """[(band index, label, codes caption)] for one group, in plot order."""
    return [(i, b[0], b[2]) for i, b in enumerate(BANDS) if b[1] == key]
