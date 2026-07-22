#!python3

from scipy import stats
import argparse
import random
import numpy as np
import pandas as pd
import researchpy as rp
import statsmodels.formula.api as smf

GET_AIC = False


def showDfInfo(df):
    df.info()
    rp.codebook(df)


def mixedEffectRegression(df, var, cont_inputs, cat_inputs):
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
                        ).fit(reml=(not GET_AIC))
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

    # AIC, BIC
    if GET_AIC:
        print(f"AIC: {model.aic:0.2f}")
        print(f"BIC: {model.bic:0.2f}")

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
    print(f"Null Model ICC: {icc_null:0.4f}")

    # ANova test
    ols_model = smf.ols(regression_expr, df).fit()
    lr_stat = 2 * (model.llf - ols_model.llf)
    df_diff = model.df_modelwc - ols_model.df_model

    p_value = stats.chi2.sf(lr_stat, df_diff)

    print(f"ANOVA lr_stat {lr_stat} p-value: {p_value}")

    filesafe_var = "".join(c for c in var
                           if c.isalpha() or c.isdigit() or c == ' ').rstrip()
    rand_df.to_csv(f"regress/{filesafe_var}_outlier.csv")
    return model


def olsRegression(df, var, cont_inputs, cat_inputs):
    output = [var]
    escaped_cont = [f"Q('{input}')" for input in cont_inputs]
    escaped_cat = [f"C(Q('{input}'))" for input in cat_inputs]
    inputString = ' + '.join(escaped_cat + escaped_cont)
    regression_expr = f"Q('{var}') ~ {inputString}",

    df = df[cont_inputs + cat_inputs + output].dropna()

    model = smf.ols(regression_expr, df).fit()
    print(model.summary())


def rk_model(df, var, drop_black):
    print("*** *** RK Model next -- ---")
    df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]
    if drop_black:
        df = df[df['black_african_american'] >= 20]
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


def aw_model(df, var, drop_black, noscore_col):
    print("*** *** AW Model next -- ---")
    df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]
    if drop_black:
        df = df[df['black_african_american'] > 20]
    df['class_of_from_0'] = df['class_of'] - np.min(df['class_of'])
    mixedEffectRegression(
        df,
        var,
        cont_inputs=[
            # 'spend_grp_ex_ell_speced_comp1k',
            # 'spend_grp_spec_ed1k',
            'pct_low_income5',
            'pct_hc5',
            'pct_sped5',
            'pct_ell5',
            'pct_asian5',
            'pct_aian5',
            'pct_black_aa5',
            'pct_nhpi5',
            'pct_two_or_more_races5',
            'pct_hispanic_latino_any_race5',
            'class_of_from_0',
            # 'at_or_after_2021',
            'pct_class_teacher_gt_bachelors5',
            'class_teacher_exp_avg',
            'principal_exp_avg5',
            # 'attendance_all5',
            # 'attendance_concern',
            # 'black_aa_math_pct_noscore5',
            noscore_col,
            'bldg_staff_abschurn_0',
            'is_regular',
        ],
        cat_inputs=[
            'ms_assignment',
            # 'region',
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

    df['class_of_from_0'] = df['class_of'] - np.min(df['class_of'])
    df['spend_grp_ex_ell_speced_comp1k'] = (
        df['spend_grp_ex_ell_speced_comp'] / 1000)
    df['spend_grp_spec_ed1k'] = df['spend_grp_spec_ed'] / 1000
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
    df['attendance_black_aa5'] = (
        df['attendance_Black/ African American_percent'] * 20)
    df['attendance_all5'] = (
        df['attendance_All Students_percent'] * 20)
    df['attendance_concern'] = np.where(
        df['attendance_All Students_percent'].fillna(1) < .75, 1, 0)
    df['black_aa_math_pct_noscore5'] = (
        df['SBAC_ELA_Black/ African American_pct_noscore'] * 20)

    df['black_aa_many_noscore'] = np.where(
        df['SBAC_ELA_Black/ African American_pct_noscore'] > .1, 1, 0)

    df['all_many_noscore'] = np.where(
        df['SBAC_ELA_All Students_pct_noscore'] > .1, 1, 0)

    df['bldg_staff_added_0'] = df['bldg_staff_added'].fillna(0)
    df['bldg_staff_lost_0'] = df['bldg_staff_lost'].fillna(0)
    df['bldg_staff_abschurn_0'] = (
        df['bldg_staff_added_0'] + df['bldg_staff_lost_0'])

    df['principal_exp_avg5'] = df['principal_exp_avg'] / 5

    #          'pct_black_aa5',
    #          'attendance_all5',
    #          'black_aa_math_pct_noscore5',
    #          ]].corr())

    # rk_model(
    #     df,
    #     'SBAC_ELA_Black/ African American_pct_met_standard_numeric',
    #     True)
    # rk_model(
    #     df,
    #     'SBAC_Math_Black/ African American_pct_met_standard_numeric',
    #     True)

    # rk_model(
    #     df,
    #     'SBAC_ELA_All Students_pct_met_standard_numeric',
    #     False)
    # rk_model(
    #     df,
    #     'SBAC_Math_All Students_pct_met_standard_numeric',
    #     False)

    # df = df[df['at_or_after_2021'] == 1]
    aw_model(
        df,
        'SBAC_ELA_Black/ African American_pct_met_standard_numeric',
        True,
        'black_aa_many_noscore',
    )
    aw_model(
        df,
        'SBAC_Math_Black/ African American_pct_met_standard_numeric',
        True,
        'black_aa_many_noscore',
    )

    aw_model(
        df,
        'SBAC_ELA_All Students_pct_met_standard_numeric',
        False,
        'all_many_noscore',
    )
    aw_model(
        df,
        'SBAC_Math_All Students_pct_met_standard_numeric',
        False,
        'all_many_noscore',
    )

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
