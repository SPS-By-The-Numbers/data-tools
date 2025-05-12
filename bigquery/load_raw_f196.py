from google.cloud import bigquery

client = bigquery.Client()


TABLE_INFO = {
    # Domain tables
    "activity": {
        'is_domain': True,
        'cluster': 'school_year,activity_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
        ]
    },
    "ccddd": {
        'is_domain': True,
        'cluster': 'school_year,ccddd,county_code,district_code',
        'in-year': ['2013-2014']
    },
    "county": {
        'is_domain': True,
        'cluster': 'school_year,county_code',
        'in-year': []
    },
    "fund": {
        'is_domain': True,
        'cluster': 'school_year,fund_code',
        'in-year': []
    },
    "item_dict": {
        'is_domain': True,
        'cluster': 'school_year,item_code',
        'in-year': [
        ]
    },
    "object": {
        'is_domain': True,
        'cluster': 'school_year,object_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
        ]
    },
    "program": {
        'is_domain': True,
        'cluster': 'school_year,program_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
        ]
    },
    "revenue": {
        'is_domain': True,
        'cluster': 'school_year,revenue_code',
        'in-year': []
    },

    # Line items
    "capital_project_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    },
    "debt_service_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    },
    "general_fund_expenditures": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,object_code,activity_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    },
    "general_fund_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    },
    "revenues_and_expenditures": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,activity_code,revenue_code',
        'in-year': [
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    },
    "item_numbers": {
        'is_domain': False,
        'cluster': 'school_year,item_code,fund_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    },
    "trans_vehicle_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code',
        'in-year': [
            '2013-2014',
            '2014-2015',
            '2015-2016',
            '2016-2017',
            '2017-2018',
            '2018-2019',
            '2019-2022',
            '2022-2023',
            '2023-2024',
        ]
    }
}

GS_SAFS_ROOT = "gs://sps-btn-data-all-data/processed/safs"

SAFS_TEMPL = "{root}/{safs_type}/{safs_type}-{year}-{tablename}.avro"

LOAD_QUERY_TEMPLATE = (
    """
    DROP TABLE IF EXISTS `sps-btn-data.raw_safs.{tablename}`;

    LOAD DATA INTO `sps-btn-data.raw_safs.{tablename}`
    CLUSTER BY {cluster}
    FROM FILES(
        format='AVRO',
        uris = {uri_list}
    )
    """)


def make_gs_url_list(tablename, info, safs_type):
    return [SAFS_TEMPL.format(year=year,
                              tablename=tablename,
                              safs_type=safs_type,
                              root=GS_SAFS_ROOT)
            for year in info['in-year']]


def make_query(tablename, info, safs_type, uri_list):
    if info["is_domain"]:
        bq_tablename = f'{safs_type}_d_{tablename}'
    else:
        bq_tablename = f'{safs_type}_{tablename}'
    return LOAD_QUERY_TEMPLATE.format(
        tablename=bq_tablename,
        cluster=info["cluster"],
        uri_list=uri_list)


def load_table(tablename, info, safs_type):
    url_list = make_gs_url_list(tablename, info, safs_type)
    if not url_list:
        print(f"Skipping {safs_type} {tablename}. No source urls")
        return

    query = make_query(tablename, info, safs_type, url_list)
    print("query: ", query)
    query_job = client.query(query)  # API request
    rows = query_job.result()  # Waits for query to finish
    print("results: ")
    for row in rows:
        print("row name: ", row.name)


def main():
    for tablename, info in TABLE_INFO.items():
        load_table(tablename, info, 'f196')


main()
