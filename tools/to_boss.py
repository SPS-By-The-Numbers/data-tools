import pandas as pd


def main():
    in_df = pd.read_csv('wide.csv')
    in_df['student_teacher_ratio'] = (
        in_df['all_students'] / in_df['class_teacher_fte'])
    in_df['spend_per_pupil'] = (
        in_df['total_spend'] / in_df['all_students'])
    df = in_df[[
        'class_of',
        'school_code',
        'school_name',
        'type',
        'all_students',
        'total_spend',
        'spend_per_pupil',
        'spend_grp_ex_ell_speced_comp',
        'spend_grp_spec_ed',
        'spend_grp_title1_lap_ble',
        'class_teacher_fte',
        'student_teacher_ratio',
        'pct_students_with_disabilities',
        'pct_section_504',
        'pct_english_language_learners',
        'pct_low_income',
        'pct_highly_capable',
        'pct_black_african_american',
        'pct_native_hawaiian_other_pacific',
        'pct_hispanic_latino_of_any_race',
        'pct_american_indian_alaskan_native',
        'pct_asian',
        'pct_two_or_more_races',
        'SBAC_Math_All Students_pct_met_standard_numeric',
        'SBAC_Math_Black/ African American_pct_met_standard_numeric',
        'SBAC_Math_White_pct_met_standard_numeric',
        'SBAC_ELA_All Students_pct_met_standard_numeric',
        'SBAC_ELA_Black/ African American_pct_met_standard_numeric',
        'SBAC_ELA_White_pct_met_standard_numeric',
    ]]
    df.columns = [
        'class_of',
        'school_code',
        'school',
        'type',
        'Student headcount (not AAFTE)',
        ('"Actuals allocated to School (f196) EXCLUDES 31% '
         'of Budget in District Office!"'),
        'Per-pupil Spending',
        'Per-pupil Spend excl SpecEd+Comp/Title1+LAP+Bi-ling',
        'Per-pupil Spend SpecEd + Compensatory',
        'Per-pupil Spend Title1 LAP Bi-Ling',
        'classroom teacher fte (s275)',
        'Student : Teacher Ratio',
        '% students with disabilities',
        '% section 504',
        '% english language learners',
        '% low income',
        '% highly capable',
        '% black / african american',
        '% native hawaiian / other pacific',
        '% hispanic latino of any race',
        '% american indian / alaskan native',
        '% asian',
        '% two or more races',
        'Math All Students Met Standard',
        'Math Black/African-American Met Standard',
        'Math White Met Standard',
        'ELA All Students Met Standard',
        'ELA Black/African- American Met Standard',
        'ELA White Met Standard',
    ]
    df = df[df['school'] != 'District Total']
    print(df.dropna())
    df.to_csv('boss.csv')


if __name__ == '__main__':
    main()
