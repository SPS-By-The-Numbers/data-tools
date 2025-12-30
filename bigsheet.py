#!python3

import argparse
import pandas as pd
import numpy as np
import statsmodels.api as sm


def orderColumnName(raw_f):
    fields = list(raw_f)
    f = fields.pop(0)
    fields.append(f)
    return fields


def moveToFront(df, col_name):
    col = df.pop(col_name)
    df.insert(0, col_name, col)


def doStats(df, var):
    output = [
        var
    ]
    inputs = [
        # "fte_per_pupil",
        # "spend_per_pupil",
        # "pct_military_parent",
        # "pct_migrant",
        "pct_low_income",
        # "pct_homeless",
        # "pct_foster_care",
        # "pct_mobile",
        # "pct_section_504",
        "pct_highly_capable",
        "pct_english_language_learners",
        "pct_students_with_disabilities",
        # "pct_female",
        # "pct_male",
        # "pct_gender_x",
        # "pct_white",
        "pct_black_african_american",
        "pct_native_hawaiian_other_pacific",
        "pct_hispanic_latino_of_any_race",
        "pct_asian",
        "pct_two_or_more_races",

        # Year of graduation
        "class_of_normalized",

        # Regions
        "r_NW",
        "r_NE",
        "r_SE",
        "r_SW",
        # "r_Central",

        # School type
        "is_regular",
        "K-8",
        "Highschool",
        "Middle",
        # "Elementary",
    ]

    df['class_of_normalized'] = df['class_of'] / df['class_of'].max()
    df['school_code_normalized'] = df['school_code'] / df['school_code'].max()

    # filter data
    # df = df[(df['class_of'] > 2021) & (df['type'] != 'Other')]
    df = df[(df['type'] != 'Other')]

    # Drop HCC Schools.
    # df = df[(df['school_code'] != 5292) & (df['school_code'] != 5488) &
    #        (df['school_code'] != 2141)]

    # Only Elementary
    df = df[(df['Elementary'] == 1)]

    df = df[output + inputs].dropna()

    y = df[output]
    X = df[inputs]

    X = sm.add_constant(X)
    model = sm.OLS(y, X).fit()
    print(model.summary())


def select_assessments(df):
    logical_key = [
        'class_of',
        'school_code',
        'test_administration',
        'test_subject',
        'student_group'
    ]
    values = [
        'pct_met_foundational_numeric',
        'pct_met_standard_numeric',
        'pct_met_foundational_numeric_nodat',
        'pct_met_standard_numeric_nodat',
    ]

    # Subset the columns and don't keep anything with an incomplete
    # logical key or no values.
    df = (df[[*logical_key, *values]]
          .dropna(subset=logical_key)
          .dropna(subset=values, how="all"))

    df = df.pivot(
        index=[
            'class_of',
            'school_code',
        ],
        columns=[
            'test_administration',
            'test_subject',
            'student_group',
        ],
        values=[
            'pct_met_foundational_numeric',
            'pct_met_standard_numeric',
            'pct_met_foundational_numeric_nodat',
            'pct_met_standard_numeric_nodat',
        ]
    ).reset_index()

    df.columns = [
        '_'.join([c for c in orderColumnName(col) if c]).strip()
        for col in df.columns.values]
    return df


def main():
    parser = argparse.ArgumentParser(
        prog='bigsheet',
        description='Converts and access database to avro format')
    parser.add_argument('--vitals', required=True,
                        help='csv with vitals by school')
    parser.add_argument('--assessment', required=True,
                        help='csv with assessment data')
    args = parser.parse_args()

    # School type indicator vars.
    vitals_df = pd.read_csv(args.vitals)
    vitals_df['OtherSchool'] = np.where(vitals_df['type'] == 'Other', 1, 0)
    vitals_df['K-8'] = np.where(vitals_df['type'] == 'K-8', 1, 0)
    vitals_df['Highschool'] = np.where(vitals_df['type'] == 'Highschool', 1, 0)
    vitals_df['Middle'] = np.where(vitals_df['type'] == 'Middle', 1, 0)
    vitals_df['Elementary'] = np.where(vitals_df['type'] == 'Elementary', 1, 0)

    # Region indicator vars.
    vitals_df['r_Invalid'] = np.where(vitals_df['region'] == 'Invalid', 1, 0)
    vitals_df['r_NW'] = np.where(vitals_df['region'] == 'NW', 1, 0)
    vitals_df['r_NE'] = np.where(vitals_df['region'] == 'NE', 1, 0)
    vitals_df['r_Central'] = np.where(vitals_df['region'] == 'Central', 1, 0)
    vitals_df['r_SW'] = np.where(vitals_df['region'] == 'SW', 1, 0)
    vitals_df['r_SE'] = np.where(vitals_df['region'] == 'SE', 1, 0)
    vitals_df['r_Other'] = np.where(vitals_df['region'] == 'Other', 1, 0)

    assessment_df = pd.read_csv(args.assessment)
    joined_df = select_assessments(assessment_df)
    joined_df = pd.merge(vitals_df, joined_df,
                         how="outer",
                         on=['class_of', 'school_code'])

    # Reorder the columns.
    moveToFront(joined_df, 'school_code')
    moveToFront(joined_df, 'is_regular')
    moveToFront(joined_df, 'type')
    moveToFront(joined_df, 'school_name')
    moveToFront(joined_df, 'class_of')

    # Do stats
    doStats(
        joined_df,
        # 'WCAS_Science_All Students_pct_met_standard_numeric'
        # 'SBAC_Math_All Students_pct_met_standard_numeric'
        'SBAC_Math_Black/ African American_pct_met_standard_numeric'
    )

    joined_df.to_csv('output.csv')


if __name__ == '__main__':
    main()
