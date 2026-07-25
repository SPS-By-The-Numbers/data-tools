"""Shared logic for publishing the bigsheet static inputs as BigQuery
external tables (website functions/src/bigsheet migration, task T0.2).

Two consumers:
  - publish_bigsheet_inputs.sh  -> build_staging(): writes the seven CSVs to a
    staging dir (slim + `_csv_row`-indexed for the three pivot-order-sensitive
    inputs; verbatim for the four pass-through inputs).
  - create_bigsheet_input_tables.sh -> emit_ddl(): prints CREATE OR REPLACE
    EXTERNAL TABLE statements with explicit schemas.

`sanitizeName` MUST stay byte-identical to functions/src/bigsheet/names.ts:
every run of non-[A-Za-z0-9_] -> single '_'; prefix '_' if it starts with a
digit. (No trailing-underscore stripping -- the golden-diff harness applies the
same rule to the golden headers, so any transform here must match there.)
"""
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

GCS_PREFIX = 'gs://sps-by-the-numbers-public/static/bigsheet-inputs'
DATASET = 'sps-btn-data.bigsheet_inputs'
DATA = Path('data/sps')


def sanitize_name(raw):
    s = re.sub(r'[^A-Za-z0-9_]+', '_', str(raw))
    if s and s[0].isdigit():
        s = '_' + s
    return s


# ---- The three pivot-order-sensitive inputs: slim + _csv_row -----------------
# _csv_row is the 0-based pd.read_csv row index, i.e. the physical CSV order the
# pandas pivot sees. Column order below IS the external-table schema order.

def _slim_map_hc():
    df = pd.read_csv(DATA / 'map/map-score-2017-2024-average-hc.csv')
    out = pd.DataFrame({
        'school_code': df['school_code'],
        'grade': df['grade'],
        'season': df['season'],
        'academic_subject': df['AcademicSubject'],
        'avg_rit_score': df['Average of RITScore'],
        'stddev_rit_score': df['StdDev of RITScore'],
    })
    return out


def _slim_map_nonhc():
    df = pd.read_csv(DATA / 'map/map-score-2017-2024-average-nonhc.csv')
    out = pd.DataFrame({
        'school_code': df['school_code'],
        'grade': df['Grade'],
        'season': df['Season'],
        'academic_subject': df['MAP Academic Subject'],
        'avg_rit_score': df['Average RIT Score'],
        'stddev': df['Std Deviation'],
        'number_of_students': df['Number of Students'],
    })
    return out


def _slim_sqss():
    df = pd.read_csv(DATA / 'sqss/sqss.csv')
    out = pd.DataFrame({
        'class_of': df['class_of'],
        'school_code': df['school_code'],
        'student_group': df['student_group'],
        'measure': df['measure'],
        'percent': df['percent'],
        'numerator': df['numerator'],
        'denominator': df['denominator'],
    })
    return out


# schema for the slim tables: (name, bq_type); _csv_row prepended in build.
SLIM = {
    'map_hc': (_slim_map_hc, [
        ('school_code', 'INT64'), ('grade', 'INT64'), ('season', 'STRING'),
        ('academic_subject', 'STRING'), ('avg_rit_score', 'FLOAT64'),
        ('stddev_rit_score', 'FLOAT64')]),
    # nonhc value columns carry suppression markers ("n<10"), so pandas reads
    # them as object -> the golden keeps the raw strings. Type them STRING; the
    # golden diff compares numerically-with-tolerance for the numeric cells.
    'map_nonhc': (_slim_map_nonhc, [
        ('school_code', 'INT64'), ('grade', 'INT64'), ('season', 'STRING'),
        ('academic_subject', 'STRING'), ('avg_rit_score', 'STRING'),
        ('stddev', 'STRING'), ('number_of_students', 'STRING')]),
    'sqss': (_slim_sqss, [
        ('class_of', 'INT64'), ('school_code', 'INT64'),
        ('student_group', 'STRING'), ('measure', 'STRING'),
        ('percent', 'FLOAT64'), ('numerator', 'FLOAT64'),
        ('denominator', 'FLOAT64')]),
}


# ---- The four pass-through inputs: copied verbatim ---------------------------
# (src basename under data/sps, published basename, explicit schema in file
# column order). Pass-through schema names for bex use sanitize_name(header) so
# a `SELECT * EXCEPT(school_code)` in the generator yields golden-matching
# names. FLOAT64 unless pandas inferred object/str (see bigsheet.py golden).

_BEX_SRC = 'building/bex-vi-historic-building-scores.csv'
_BEX_STRING_COLS = {'Last Major Update', 'Scope of Work'}


def _bex_schema():
    header = pd.read_csv(DATA / _BEX_SRC, nrows=0).columns.tolist()
    schema = []
    for h in header:
        if h == 'school_code':
            schema.append(('school_code', 'INT64'))
        else:
            t = 'STRING' if h in _BEX_STRING_COLS else 'FLOAT64'
            schema.append((sanitize_name(h), t))
    return schema


PASSTHROUGH = {
    'bex': ('building/bex-vi-historic-building-scores.csv', _bex_schema),
    'utilization_condition': ('building/utilization_condition.csv', lambda: [
        ('school_code', 'INT64'), ('pct_2025_utilization', 'FLOAT64'),
        ('pct_building_condition', 'FLOAT64'),
        ('learning_environment_score', 'FLOAT64'),
        ('_2022_building_condition_score', 'FLOAT64')]),
    'income_by_school': ('building/income_by_school.csv', lambda: [
        ('es_zone', 'STRING'), ('school_code', 'INT64'),
        ('area_worker_earnings_median', 'FLOAT64'),
        ('area_percapita_income', 'FLOAT64')]),
    'building_transitions': ('s275/building_transitions.csv', lambda: [
        ('class_of', 'INT64'), ('duty_root', 'INT64'),
        ('school_code', 'INT64'), ('transfer_in', 'INT64'),
        ('school', 'STRING'), ('duty_name', 'STRING'),
        ('duty_name_category', 'STRING'), ('transfer_out', 'INT64'),
        ('hire', 'INT64'), ('depart', 'INT64')]),
}


def table_schema(table):
    """Full ordered [(name, type), ...] incl. _csv_row for slim tables."""
    if table in SLIM:
        return [('_csv_row', 'INT64')] + SLIM[table][1]
    return PASSTHROUGH[table][1]()


ALL_TABLES = list(SLIM) + list(PASSTHROUGH)


# Columns that must serialize as clean integers (a stray NaN elsewhere in the
# source can otherwise coerce the whole column to float -> "2138.0", which
# fails INT64 parsing on the external table). pandas nullable Int64 writes
# "2138" and "" (for NaN).
_INT_COLS = {'school_code', 'grade', 'class_of', '_csv_row'}


def build_staging(staging_dir):
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    for name, (fn, _schema) in SLIM.items():
        df = fn().reset_index(drop=True)
        df.insert(0, '_csv_row', range(len(df)))
        for c in df.columns:
            if c in _INT_COLS:
                df[c] = df[c].astype('Int64')
        df.to_csv(staging / f'{name}.csv', index=False)
        print(f'  built slim {name}.csv ({len(df)} rows, +_csv_row)')
    for name, (src, _schema) in PASSTHROUGH.items():
        # Byte-for-byte copy: a pandas round-trip would coerce INT columns that
        # carry a stray NaN to float ("1.0"), which fails INT64 parsing.
        shutil.copyfile(DATA / src, staging / f'{name}.csv')
        n = sum(1 for _ in open(DATA / src)) - 1
        print(f'  copied {name}.csv ({n} rows) from {src}')


def emit_ddl():
    lines = [f'CREATE SCHEMA IF NOT EXISTS `{DATASET}`;', '']
    for table in ALL_TABLES:
        cols = ',\n  '.join(f'`{n}` {t}' for n, t in table_schema(table))
        uri = f'{GCS_PREFIX}/{table}.csv'
        lines.append(
            f'CREATE OR REPLACE EXTERNAL TABLE `{DATASET}.{table}` (\n'
            f'  {cols}\n'
            f') OPTIONS (\n'
            f"  format = 'CSV',\n"
            f"  uris = ['{uri}'],\n"
            f'  skip_leading_rows = 1\n'
            f');\n')
    return '\n'.join(lines)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'ddl':
        print(emit_ddl())
    elif len(sys.argv) > 2 and sys.argv[1] == 'stage':
        build_staging(sys.argv[2])
    else:
        sys.exit('usage: bigsheet_inputs_lib.py ddl | stage <dir>')
