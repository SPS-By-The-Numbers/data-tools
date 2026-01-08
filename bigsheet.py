#!python3

import argparse
import pandas as pd
import numpy as np


def rotateLeftColumnName(raw_f):
    """Given a set of fields post pivot, moves the first to the back"""
    fields = list(raw_f)
    f = fields.pop(0)
    fields.append(f)
    return fields


def moveToFront(df, col_name):
    col = df.pop(col_name)
    df.insert(0, col_name, col)


def join_map(df):
    hc_df = pd.read_csv('data/sps/map/map-score-2017-2024-average-hc.csv')
    hc_df = hc_df.pivot(
        index=[
            'school_code',
        ],
        columns=[
            'AcademicSubject',
            'grade',
            'season',
        ],
        values=[
            'Average of RITScore',
            'StdDev of RITScore',
        ]
    ).reset_index()
    hc_df.columns = [
        'hc_' + '_'.join(
            [str(c) for c in rotateLeftColumnName(col) if c]).strip()
        for col in hc_df.columns.values]
    hc_df.rename(columns={'hc_school_code': 'school_code'}, inplace=True)

    nonhc_df = pd.read_csv(
        'data/sps/map/map-score-2017-2024-average-nonhc.csv')
    nonhc_df = nonhc_df.pivot(
        index=[
            'school_code',
        ],
        columns=[
            'MAP Academic Subject',
            'Grade',
            'Season',
        ],
        values=[
            'Average RIT Score',
            'Std Deviation',
            'Number of Students',
        ]
    ).reset_index()
    nonhc_df.columns = [
        'nonhc_' + '_'.join(
            [str(c) for c in rotateLeftColumnName(col) if c]).strip()
        for col in nonhc_df.columns.values]
    nonhc_df.rename(columns={'nonhc_school_code': 'school_code'}, inplace=True)

    df = pd.merge(df, hc_df, on='school_code', how="left")
    df = pd.merge(df, nonhc_df, on='school_code', how='left')

    return df


def join_bex(df):
    building_df = pd.read_csv(
        'data/sps/building/bex-vi-historic-building-scores.csv')
    utilize_df = pd.read_csv(
        'data/sps/building/utilization_condition.csv')
    income_df = pd.read_csv(
        'data/sps/building/income_by_school.csv')
    df = pd.merge(df, building_df, on='school_code', how='left')
    df = pd.merge(df, utilize_df, on='school_code', how='left')
    df = pd.merge(df, income_df, on='school_code', how='left')
    return df


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

    return df


def assessments_to_wide(df):
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
        '_'.join([c for c in rotateLeftColumnName(col) if c]).strip()
        for col in df.columns.values]
    return df


def addNormalizedFields(df):
    df['num_students_normalized'] = (
        df['all_students'] / df['all_students'].max())
    df['class_of_normalized'] = df['class_of'] / df['class_of'].max()
    df['school_code_normalized'] = df['school_code'] / df['school_code'].max()
    df['ms_assignment_code_normalized'] = (
        df['ms_assignment_code'] / df['ms_assignment_code'].max()
    )

    df['class_teacher_exp_50pctile_normalized'] = (
        df['class_teacher_exp_50pctile']
        / df['class_teacher_exp_50pctile'].max())
    df['pct_class_teacher_over_bachelors'] = (
        (df['num_class_teachers_masters'] +
         df['num_class_teachers_doctors']) / df['num_class_teachers'])
    df['class_teacher_fte_per_pupil'] = (
        df['class_teacher_fte'] / df['all_students'])
    df['asst_principal_fte_per_pupil'] = (
        df['asst_principal_fte'] / df['all_students'])
    df['other_teacher_fte_per_pupil'] = (
        df['other_teacher_fte'] / df['all_students'])

    df['at_or_after_2021'] = np.where(df['class_of'] >= 2021, 1, 0)


def main():
    parser = argparse.ArgumentParser(
        prog='bigsheet',
        description='Combines multiple datafiles into one big merged dataset')
    parser.add_argument('--vitals', required=True,
                        help='csv with vitals by school')
    parser.add_argument('--assessment', required=True,
                        help='csv with assessment data')
    parser.add_argument('-w', '--write', action='store_true',
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

    vitals_df['m_Meany'] = np.where(
        vitals_df['ms_assignment_code'] == 5485, 1, 0)
    vitals_df['m_Eckstein'] = np.where(
        vitals_df['ms_assignment_code'] == 2729, 1, 0)
    vitals_df['m_JaneAddams'] = np.where(
        vitals_df['ms_assignment_code'] == 5351, 1, 0)
    vitals_df['m_Hamilton'] = np.where(
        vitals_df['ms_assignment_code'] == 2371, 1, 0)
    vitals_df['m_McClure'] = np.where(
        vitals_df['ms_assignment_code'] == 3517, 1, 0)
    vitals_df['m_RESMS'] = np.where(
        vitals_df['ms_assignment_code'] == 5486, 1, 0)
    vitals_df['m_Whitman'] = np.where(
        vitals_df['ms_assignment_code'] == 3277, 1, 0)
    vitals_df['m_AkiKurose'] = np.where(
        vitals_df['ms_assignment_code'] == 3774, 1, 0)
    vitals_df['m_Mercer'] = np.where(
        vitals_df['ms_assignment_code'] == 3095, 1, 0)
    vitals_df['m_Washington'] = np.where(
        vitals_df['ms_assignment_code'] == 4064, 1, 0)
    vitals_df['m_Denny'] = np.where(
        vitals_df['ms_assignment_code'] == 2839, 1, 0)
    vitals_df['m_Madison'] = np.where(
        vitals_df['ms_assignment_code'] == 2435, 1, 0)

    vitals_df = join_map(vitals_df)
    vitals_df = join_bex(vitals_df)

    assessment_df = pd.read_csv(args.assessment)
    selected_df = select_assessments(assessment_df)

    joined_df = assessments_to_wide(selected_df)
    joined_df = pd.merge(vitals_df, joined_df,
                         how="outer",
                         on=['class_of', 'school_code'])

    addNormalizedFields(joined_df)

    # Reorder the columns.
    moveToFront(joined_df, 'school_code')
    moveToFront(joined_df, 'is_regular')
    moveToFront(joined_df, 'type')
    moveToFront(joined_df, 'school_name')
    moveToFront(joined_df, 'class_of')

    joined_df.to_csv('wide.csv')


if __name__ == '__main__':
    main()
