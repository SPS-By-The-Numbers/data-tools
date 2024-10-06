import pandas as pd
df = pd.read_excel('copyof22-23f-196codes.xlsx', sheet_name=None)
for key in df.keys():
    df[key].to_csv('codes_{}.csv'.format(key))
