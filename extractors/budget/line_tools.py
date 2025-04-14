import re

SPACE_SPAN_TO_TOKEN = re.compile(r"\s\s+")


def tokenize_by_two_space(line):
    """For fields separated by a many spaces, break by spans of 2+ spaces"""
    return [field.strip() for field in
            re.sub(SPACE_SPAN_TO_TOKEN, "\t", line).split("\t")]
