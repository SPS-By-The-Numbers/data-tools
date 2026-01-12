#!python3

import argparse
import random
import numpy as np
# import researchpy as rp
import pandas as pd

from plotnine import (
    ggplot,
    aes,
    geom_point,
    geom_line,
    geom_text,
    facet_wrap,
    # facet_grid,
    scale_fill_gradientn,
    theme,
)


def plot_var(df, var):
    df = df[df['black_african_american'] > 20]
    df = df.dropna(subset='region')
    all_codes = df['school_code'].unique()
    shuffled = list(enumerate(all_codes))
    random.shuffle(shuffled)
    mapping = {code: index for (index, code) in shuffled}
    df = df[(df['Elementary'] == 1) | (df['K-8'] == 1)]

    my_colors = [
        "#000000",
        "#ff0000",
        "#ffff00",
        "#00ff00",
        "#00ffff",
        "#0000ff",
        "#efefef",
    ]
    df['school_color'] = df['school_code'].map(mapping)
    df["school_shape"] = np.where(df['class_of'] > 2020, 1, 2).astype(object)
    df["school_size"] = df['class_of_from_0']
    xaxis = "class_of"
    plot = (
        ggplot(df, aes(xaxis, var))
        + scale_fill_gradientn(colors=my_colors)
        + geom_point(aes(
            fill="school_color",
            # shape="school_shape",
            # size="school_size"
        ),
            size=1.5
        )
        + geom_text(aes(label='school_name'), ha='left', va='bottom', size=3)
        + geom_line(aes(group="school_name"))
        # + facet_wrap("region")
        + facet_wrap("ms_assignment")
        # + facet_grid("ms_assignment ~ at_or_after_2021")
        + theme(legend_position='none')
    )
    plot.save("my_plot.png", width=8, height=6, dpi=150)


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

    plot_var(
        df,
        # 'SBAC_ELA_Black/ African American_pct_met_standard_numeric')
        'SBAC_Math_All Students_pct_met_standard_numeric')


if __name__ == '__main__':
    main()
