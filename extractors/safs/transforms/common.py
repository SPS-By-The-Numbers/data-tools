EXTRACT_STARTING_YEAR = """
CAST(SPLIT_PART(t.school_year, '-', 1) AS INTEGER) AS school_starting_year
"""
