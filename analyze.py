#!python3

import argparse
import pandas as pd
import numpy as np
import statsmodels.api as sm
import researchpy as rp
import statsmodels.formula.api as smf


CONT_INPUTS = [
    # "fte_per_pupil",
    # "num_students_normalized",
    "all_students",
    # "class_teacher_exp_50pctile_normalized",
    "class_teacher_exp_avg",
    # "pct_class_teacher_over_bachelors",
    "class_teacher_fte_per_pupil",
    # "class_teacher_likely_early_term_fte",
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
    # "pct_native_hawaiian_other_pacific",
    # "pct_hispanic_latino_of_any_race",
    # "pct_asian",
    # "pct_two_or_more_races",
]

CATEGORICAL_INPUTS = [
    # Year of graduation
    # "class_of",
    "at_or_after_2021",

    # Regions
    # 'ms_assignment',
    # 'region',
    # "r_NW",
    # "r_NE",
    # "r_SE",
    # "r_SW",
    # "r_Central",

    # Middle schools
    # 'm_Meany',
    # 'm_Eckstein',
    # 'm_JaneAddams',
    # 'm_Hamilton',
    # 'm_McClure',
    # 'm_RESMS',
    # 'm_Whitman',
    # 'm_AkiKurose',
    # 'm_Mercer',
    # 'm_Washington',
    # 'm_Denny',
    # 'm_Madison',

    # School type
    "is_regular",
    # 'type',
    # "Elementary",
    "K-8",
    "Highschool",
    "Middle",
]


def showDfInfo(df):
    df.info()
    rp.codebook(df)


def mixedEffectRegression(df, var):
    df['at_or_after_2021'] = np.where(df['class_of'] >= 2021, 1, 0)
    # df = df[(df['school_code'] != 5292) & (df['school_code'] != 5488) &
    #         (df['school_code'] != 2141)]
    # df = df[# (df['Elementary'] == 1) |
    #         (df['K-8'] == 1) |
    #         (df['Middle'] == 1) |
    #         (df['Highschool'] == 1)
    #         ]
    output = [var]
    groups = 'school_code'
    df = df[CONT_INPUTS + CATEGORICAL_INPUTS + output + [groups]].dropna()
    escaped_cont = [f"Q('{input}')" for input in CONT_INPUTS]
    escaped_cat = [f"C(Q('{input}'))" for input in CATEGORICAL_INPUTS]
    inputString = ' + '.join(escaped_cat + escaped_cont)

    # Mixed effects.
    model = smf.mixedlm(
        f"Q('{var}') ~ {inputString}",
        df,
        groups=df[groups]).fit()
    print(model.summary())

    # Random slopes.
    model2 = smf.mixedlm(
        f"Q('{var}') ~ {inputString}",
        df,
        groups=groups,
        re_formula="Q('at_or_after_2021')"
    ).fit()
    print(model2.summary())


def olsRegression(df, var):
    output = [var]

    # filter data
    # df = df[(df['class_of'] > 2021) & (df['type'] != 'Other')]
    df['at_or_after_2021'] = np.where(df['class_of'] >= 2021, 1, 0)

    # Drop HCC Schools.
    # df = df[(df['school_code'] != 5292) & (df['school_code'] != 5488) &
    #        (df['school_code'] != 2141)]

    # Only Elementary
    # df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]

    df = df[CONT_INPUTS + CATEGORICAL_INPUTS + output].dropna()
    y = df[output]
    X = df[CONT_INPUTS + CATEGORICAL_INPUTS]

    X = sm.add_constant(X)
    model = sm.OLS(y, X).fit()
    print(model.summary())


def main():
    parser = argparse.ArgumentParser(
        prog='analyze',
        description='Converts and access database to avro format')
    parser.add_argument('--input', required=True,
                        help='bigsheet csv')
    args = parser.parse_args()

    df = pd.read_csv(args.input)

    # Do stats
    # olsRegression(
    #     joined_df,
    #     'SBAC_Math_All Students_pct_met_standard_numeric'
    # )

    mixedEffectRegression(
        df,
        # 'SBAC_Math_All Students_pct_met_standard_numeric'
        'SBAC_ELA_Black/ African American_pct_met_standard_numeric'
    )

    # mixedEffectRegression(
    #     joined_df,
    #     'class_teacher_exp_50pctile'
    # )

    # olsRegression(
    #     joined_df,
    #     'SBAC_Math_Black/ African American_pct_met_standard_numeric'
    # )
    # olsRegression(
    #     joined_df,
    #     'SBAC_ELA_All Students_pct_met_standard_numeric'
    # )
    # olsRegression(
    #     joined_df,
    #     'SBAC_ELA_Black/ African American_pct_met_standard_numeric'
    # )
    # 'WCAS_Science_All Students_pct_met_standard_numeric'


if __name__ == '__main__':
    main()
