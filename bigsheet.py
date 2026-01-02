#!python3

import argparse
import pandas as pd
import numpy as np
import statsmodels.api as sm
import researchpy as rp
# import scipy.stats as stats


def orderColumnName(raw_f):
    fields = list(raw_f)
    f = fields.pop(0)
    fields.append(f)
    return fields


def moveToFront(df, col_name):
    col = df.pop(col_name)
    df.insert(0, col_name, col)


def showDfInfo(df):
    df.info()
    rp.codebook(df)


def olsRegression(df, var):
    output = [
        var
    ]
    inputs = [
        # "fte_per_pupil",
        "num_students_normalized",
        "class_teacher_exp_50pctile_normalized",
        "pct_class_teacher_over_bachelors",
        "class_teacher_fte_per_pupil",
        "class_teacher_likely_early_term_fte",
        # "other_teacher_fte_per_pupil",
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
        # "class_of_normalized",
        "2021_or_later",

        # Regions
        # 'ms_assignment_code_normalized',
        # "r_NW",
        # "r_NE",
        # "r_SE",
        # "r_SW",
        # "r_Central",

        # Middle schools
        'm_Meany',
        'm_Eckstein',
        'm_JaneAddams',
        'm_Hamilton',
        'm_McClure',
        'm_RESMS',
        'm_Whitman',
        'm_AkiKurose',
        'm_Mercer',
        'm_Washington',
        'm_Denny',
        # 'm_Madison',

        # School type
        "is_regular",
        "K-8",
        "Highschool",
        "Middle",
        # "Elementary",
    ]

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

    # filter data
    # df = df[(df['class_of'] > 2021) & (df['type'] != 'Other')]
    df['2021_or_later'] = np.where(df['class_of'] >= 2021, 1, 0)
    # df = df[(df['type'] != 'Other')]

    # Drop HCC Schools.
    # df = df[(df['school_code'] != 5292) & (df['school_code'] != 5488) &
    #        (df['school_code'] != 2141)]

    # Only Elementary
    # df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]

    df = df[inputs + output].dropna()
    y = df[output]
    X = df[inputs]

    X = sm.add_constant(X)
    model = sm.OLS(y, X).fit()
    print(model.summary())


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
        'hc_' + '_'.join([str(c) for c in orderColumnName(col) if c]).strip()
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
            [str(c) for c in orderColumnName(col) if c]).strip()
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
    df = pd.merge(df, building_df, on='school_code', how='left')
    df = pd.merge(df, utilize_df, on='school_code', how='left')
    return df


# long should look like
# class_of, school_code, test_administration, test_subject, student_type,
# student_group, variable, value
#
# Example
#  2023, 5458, SBAC, Math, Race, All, Count, 100
#  2023, 5458, SBAC, Math, Race, All, Pct, 1.0
#  2023, 5458, SBAC, Math, Race, All, pct_met_foundational_numeric, 0.8
#
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
        '_'.join([c for c in orderColumnName(col) if c]).strip()
        for col in df.columns.values]
    return df


def melt_school_info_category(accumulate, df, student_group_type, value_name,
                              value_vars):
    df = df.melt(
        id_vars=['class_of', 'school_code'],
        value_vars=value_vars,
        var_name='student_group',
        value_name=value_name
    )
    df['student_group_type'] = student_group_type
    return pd.concat([accumulate, df], ignore_index=True)


def vitals_to_long(df):
    result = pd.DataFrame()
    result = melt_school_info_category(result, df, 'All', 'count', [
        'all_students'])
    result = melt_school_info_category(result, df, 'homeless', 'count', [
        'homeless'])
    result = melt_school_info_category(result, df, 'Migrant', 'count', [
        'migrant'])
    result = melt_school_info_category(result, df, 'Military', 'count', [
        'military_parent'])
    result = melt_school_info_category(result, df, 'FRL', 'count', [
        'low_income'])
    result = melt_school_info_category(result, df, 'Foster', 'count', [
        'foster_care'])
    result = melt_school_info_category(result, df, 'Mobile', 'count', [
        'mobile'])
    result = melt_school_info_category(result, df, 's504', 'count', [
        'section_504'])
    result = melt_school_info_category(result, df, 'ELL', 'count', [
        'english_language_learners'])
    result = melt_school_info_category(result, df, 'HCC', 'count', [
        'highly_capable'])
    result = melt_school_info_category(result, df, 'SWD', 'count', [
        'students_with_disabilities'])
    result = melt_school_info_category(result, df, 'Gender', 'count', [
        'female', 'gender_x', 'male'])

    result = melt_school_info_category(result, df, 'Race', 'count', [
        'white', 'black_african_american', 'native_hawaiian_other_pacific',
        'hispanic_latino_of_any_race', 'american_indian_alaskan_native',
        'asian', 'two_or_more_races'])

    return result


def main():
    parser = argparse.ArgumentParser(
        prog='bigsheet',
        description='Converts and access database to avro format')
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
    long_df = select_assessments(assessment_df)
    # showDfInfo(long_df)

    wide_df = assessments_to_wide(long_df)
    wide_df = pd.merge(vitals_df, wide_df,
                       how="outer",
                       on=['class_of', 'school_code'])

    # Reorder the columns.
    moveToFront(wide_df, 'school_code')
    moveToFront(wide_df, 'is_regular')
    moveToFront(wide_df, 'type')
    moveToFront(wide_df, 'school_name')
    moveToFront(wide_df, 'class_of')

    if args.write:
        wide_df.to_csv('wide.csv')

    # Do stats
    olsRegression(
        wide_df,
        'SBAC_Math_All Students_pct_met_standard_numeric'
    )
    # olsRegression(
    #     wide_df,
    #     'SBAC_Math_Black/ African American_pct_met_standard_numeric'
    # )
    # olsRegression(
    #     wide_df,
    #     'SBAC_ELA_All Students_pct_met_standard_numeric'
    # )
    # olsRegression(
    #     wide_df,
    #     'SBAC_ELA_Black/ African American_pct_met_standard_numeric'
    # )
    # 'WCAS_Science_All Students_pct_met_standard_numeric'


if __name__ == '__main__':
    main()
