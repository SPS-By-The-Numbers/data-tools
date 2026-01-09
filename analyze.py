#!python3

from scipy import stats
import argparse
import numpy as np
import pandas as pd
import researchpy as rp
import statsmodels.formula.api as smf


CONT_INPUTS = [
    # "fte_per_pupil",
    # "num_students_normalized",
    # "all_students",
    # "class_teacher_exp_50pctile_normalized",
    # "class_teacher_exp_avg",
    # "pct_class_teacher_over_bachelors",
    # "class_teacher_fte_per_pupil",
    # "class_teacher_likely_early_term_fte",
    # "other_teacher_fte_per_pupil",
    # "spend_per_pupil",
    # "pct_military_parent",
    # "pct_migrant",
    # "pct_low_income",
    # "pct_homeless",
    # "pct_foster_care",
    # "pct_mobile",
    # "pct_section_504",
    # "pct_highly_capable",
    # "pct_english_language_learners",
    # "pct_students_with_disabilities",
    # "pct_female",
    # "pct_male",
    # "pct_gender_x",
    # "pct_white",
    # "pct_black_african_american",
    # "pct_native_hawaiian_other_pacific",
    # "pct_american_indian_alaskan_native",
    # "pct_hispanic_latino_of_any_race",
    # "pct_asian",
    # "pct_two_or_more_races",

    # "pct_class_teacher_over_bachelors",
    # "class_teacher_exp_avg",
    # "class_of",
]

CATEGORICAL_INPUTS = [
    # Year of graduation
    # "at_or_after_2021",

    # Regions
    # 'ms_assignment',
    # 'region',
    "r_NW",
    "r_NE",
    "r_SE",
    "r_SW",
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
    # "K-8",
    # "Highschool",
    # "Middle",
]


def showDfInfo(df):
    df.info()
    rp.codebook(df)


def mixedEffectRegression(df, var,
                          cont_inputs=CONT_INPUTS,
                          cat_inputs=CATEGORICAL_INPUTS):
    df[var] = df[var] * 100
    output = [var]
    groups = 'school_name'
    df = df[cont_inputs + cat_inputs + output + [groups]].dropna()
    escaped_cont = [f"Q('{input}')" for input in cont_inputs]
    escaped_cat = [f"C(Q('{input}'))" for input in cat_inputs]
    inputString = ' + '.join(escaped_cat + escaped_cont)
    regression_expr = f"Q('{var}') ~ {inputString}"

    # rp.codebook(df)

    # Mixed effects.
    model = smf.mixedlm(regression_expr,
                        df,
                        groups=df[groups]
                        ).fit()
    print(model.summary())

    rand_effects = model.random_effects

    rand_df = (
        pd.DataFrame.from_dict(rand_effects, orient="index")
        .reset_index()
        .rename(columns={"index": "school_id"})
    )

    rand_df = rand_df.rename(columns={"Group": "rand_intercept"})

    median = rand_df["rand_intercept"].median()
    mad = np.median(np.abs(rand_df["rand_intercept"] - median))

    # 0.6745 is apparently the scaling factor for a median absolute deviation?
    #
    # https://en.wikipedia.org/wiki/Median_absolute_deviation
    rand_df["rand_z_robust"] = (
        0.6745 * (rand_df["rand_intercept"] - median) / mad
    )

    rand_df["school_outlier"] = rand_df["rand_z_robust"].abs() > 2
    variance_school = model.cov_re.iloc[0, 0]

    # Residual (within-school) variance
    variance_resid = model.scale

    # ICC
    icc = variance_school / (variance_school + variance_resid)
    print(f"ICC: {icc:0.4f}")

    null_model = smf.mixedlm(
        f"Q('{var}') ~ 1",
        data=df,
        groups=df[groups]
    ).fit()

    icc_null = (
        null_model.cov_re.iloc[0, 0] /
        (null_model.cov_re.iloc[0, 0] + null_model.scale)
    )
    print(f"Null Model ICC: {icc:0.4f}")

    # ANova test
    ols_model = smf.ols(regression_expr, df).fit()
    lr_stat = 2 * (model.llf - ols_model.llf)
    df_diff = model.df_modelwc - ols_model.df_model

    p_value = stats.chi2.sf(lr_stat, df_diff)

    print(f"ANOVA lr_stat {lr_stat} p-value: {p_value}")

    rand_df.to_csv("outlier.csv")
    return model


def olsRegression(df, var,
                  cont_inputs=CONT_INPUTS,
                  cat_inputs=CATEGORICAL_INPUTS):
    output = [var]
    escaped_cont = [f"Q('{input}')" for input in cont_inputs]
    escaped_cat = [f"C(Q('{input}'))" for input in cat_inputs]
    inputString = ' + '.join(escaped_cat + escaped_cont)
    regression_expr = f"Q('{var}') ~ {inputString}",

    df = df[cont_inputs + cat_inputs + output].dropna()

    model = smf.ols(regression_expr, df).fit()
    print(model.summary())


def rk_model(df, var):
    df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]
    df = df[df['black_african_american'] > 20]
    df['class_of_from_0'] = df['class_of'] - np.min(df['class_of'])
    mixedEffectRegression(
        df,
        var,
        cont_inputs=[
            'pct_low_income5',
            'pct_hc5',
            'pct_ell5',
            'pct_sped5',
            'pct_asian5',
            'pct_aian5',
            'pct_black_aa5',
            'pct_nhpi5',
            'pct_two_or_more_races5',
            'principal_exp_avg',
            'pct_hispanic_latino_any_race5',
            'class_of_from_0',
            'pct_class_teacher_gt_bachelors5',
            'class_teacher_exp_avg',
            'is_regular',
        ],
        cat_inputs=[
            'region',
        ]
    )


def rk_model_spend(df, var):
    df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]
    mixedEffectRegression(
        df,
        var,
        cont_inputs=[
            'spend_grp_spec_ed',
            'pct_low_income5',
            'pct_hc5',
            'pct_asian5',
            'pct_aian5',
            'pct_black_aa5',
            'pct_nhpi5',
            'pct_two_or_more_races5',
            'pct_hispanic_latino_any_race5',
            'class_of',
            'pct_class_teacher_gt_bachelors5',
            'class_teacher_exp_avg',
            'is_regular',
        ],
        cat_inputs=[
            'region',
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        prog='analyze',
        description='Converts and access database to avro format')
    parser.add_argument('--input', required=True,
                        help='bigsheet csv')
    args = parser.parse_args()

    df = pd.read_csv(args.input)

    df['pct_low_income5'] = df['pct_low_income'] * 20
    df['pct_hc5'] = df['pct_highly_capable'] * 20
    df['pct_ell5'] = df['pct_english_language_learners'] * 20
    df['pct_sped5'] = df['pct_students_with_disabilities'] * 20
    df['pct_asian5'] = df['pct_asian'] * 20
    df['pct_aian5'] = df['pct_american_indian_alaskan_native'] * 20
    df['pct_black_aa5'] = df['pct_black_african_american'] * 20
    df['pct_nhpi5'] = df['pct_native_hawaiian_other_pacific'] * 20
    df['pct_two_or_more_races5'] = df['pct_two_or_more_races'] * 20
    df['pct_hispanic_latino_any_race5'] = (
        df['pct_hispanic_latino_of_any_race'] * 20
    )
    df['pct_class_teacher_ge_bachelors5'] = (
        df['pct_class_teacher_ge_bachelors'] * 20)
    df['pct_class_teacher_gt_bachelors5'] = (
        df['pct_class_teacher_gt_bachelors'] * 20)

    rk_model(df,
             'SBAC_ELA_Black/ African American_pct_met_standard_numeric')
    # 'SBAC_ELA_All Students_pct_met_standard_numeric')
    # rk_model_spend(df,
    #

    # filter data
    # df = df[(df['class_of'] > 2021) & (df['type'] != 'Other')]

    # Drop HCC Schools.
    # df = df[(df['school_code'] != 5292) & (df['school_code'] != 5488) &
    #        (df['school_code'] != 2141)]

    # df = df[(df['region'] != 'Other')]
    # df = df[(df['type'] == 'Elementary')]

    # Only Elementary
    # df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]
    # df = df[(df['class_of'] == 2025)]

    # olsRegression(
    #    df,
    #    'spend_grp_ex_ell_speced_comp',
    #    cont_inputs=[
    #        'pct_black_african_american',
    #        'pct_hispanic_latino_of_any_race',
    #        'pct_low_income',
    #        'log_enrollment',
    #    ],
    #    cat_inputs=[
    #    ]
    # )


if __name__ == '__main__':
    main()
