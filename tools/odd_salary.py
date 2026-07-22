#!python3

import pandas as pd
import numpy as np
import researchpy as rp
import statsmodels.formula.api as smf


CONT_INPUTS = [
]


CATEGORICAL_INPUTS = [
    'race',
]


def findOutliers(df, varRoot):
    delta = f"delta_{varRoot}_1fte"
    pct = f"pct_chg_{varRoot}"
    z = (df[delta] - df[delta].mean()) / df[delta].std()
    return df[(z > 2) | (df[pct] > 0.5)]


def olsRegression(df, var):
    output = [var]

    df = df[CONT_INPUTS + CATEGORICAL_INPUTS + output].dropna()
    print(df.head())
    escaped_cont = [f"Q('{input}')" for input in CONT_INPUTS]
    escaped_cat = [f"C(Q('{input}'))" for input in CATEGORICAL_INPUTS]
    inputString = ' + '.join(escaped_cont + escaped_cat)
    print(inputString)

    model = smf.ols(
        f"{var} ~ {inputString}",
        data=df).fit()
    return model


def main():
    df = pd.read_csv('district_office_transitions.csv')
    df['is_hispanic'] = np.where(df['is_hispanic'] == 'true', 1, 0)
    df.drop(columns=["private_employee_id_1",
                     "employee_id_1",
                     "s275_recno",
                     "full_name_1",
                     "employee_id_2",
                     "sex_1",
                     "is_hispanic_1",
                     "race_1",
                     "certificate_id_1",
                     "s275_recno_1"],
            inplace=True)
    df['delta_asssal'] = (df['total_assignment_salary_to'] -
                          df['total_assignment_salary_from'])
    df['delta_tfinsal'] = (df['total_final_salary_to'] -
                           df['total_final_salary_from'])
    df['delta_fte'] = (df['fte_to'] - df['fte_from'])
    df['pct_chg_asssal'] = (df['delta_asssal'] /
                            df['total_assignment_salary_from'])
    df['pct_chg_tfinsal'] = (df['delta_tfinsal'] /
                             df['total_final_salary_from'])
    df['delta_asssal_1fte'] = (
        (df['total_assignment_salary_to'] / df['fte_to']) -
        (df['total_assignment_salary_from'] / df['fte_from']))
    df['delta_tfinsal_1fte'] = (
        (df['total_final_salary_to'] / df['fte_to']) -
        (df['total_final_salary_from'] / df['fte_from']))

    df['act_change'] = (
        df['activity_code_from'].astype(str)
        + '->'
        + df['activity_code_to'].astype(str)
    )
    df['cost_center_change'] = (
        df['program_from'].astype(str) + '/' +
        df['activity_code_from'].astype(str)
        + '->'
        + df['program_to'].astype(str) + '/' +
        df['activity_code_to'].astype(str)
    )
    df['duty_root_change'] = (
        df['duty_root_code_from'].astype(str) + '->' +
        df['duty_root_code_to'].astype(str)
    )
    df['duty_suffix_change'] = (
        df['duty_suffix_code_from'].astype(str) + '->' +
        df['duty_suffix_code_to'].astype(str)
    )
    df['full_change'] = (
        df['cost_center_change'] + '/' +
        df['duty_root_change'] + '/' +
        df['duty_suffix_change']
    )

    # Drop bad data
    df = df.replace([np.inf, -np.inf], np.nan).dropna(axis=0)
    rp.codebook(df[[
        'delta_asssal',
        'delta_tfinsal',
        'delta_tfinsal_1fte',
        'delta_asssal_1fte',
    ]])

    asssal_outliers = findOutliers(df, 'asssal')
    # rp.codebook(asssal_outliers[['delta_asssal_1fte', 'act_change']])

    asssal_outliers.to_csv('assal_outliers.csv')

    tfinsal_outliers = findOutliers(df, 'tfinsal')
    tfinsal_outliers.to_csv('tfinsal_outliers.csv')

    asssal_model = olsRegression(asssal_outliers, 'delta_asssal_1fte')
    print(asssal_model.summary())
    tfinsal_model = olsRegression(tfinsal_outliers, 'delta_tfinsal_1fte')
    print(tfinsal_model.summary())


if __name__ == '__main__':
    main()
