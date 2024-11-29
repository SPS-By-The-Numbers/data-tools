import pandas

xlsx = pandas.ExcelFile(
    'washington_state_school_personnel_-_school_year_2022-2023.xlsx')
data = [pandas.read_excel(xlsx, sheet_name=sheet)
        for sheet in xlsx.sheet_names]
print(pandas.concat(data).to_csv())
