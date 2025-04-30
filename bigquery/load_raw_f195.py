from google.cloud import bigquery

client = bigquery.Client()


TABLE_INFO = {
    # Domain tables
    "activity": {
        'is_domain': True,
        'cluster': 'school_year,activity_code'
    },
    "ccddd": {
        'is_domain': True,
        'cluster': 'school_year,ccddd,county_code,district_code'
    },
    "county": {
        'is_domain': True,
        'cluster': 'school_year,county_code'
    },
    "fund": {
        'is_domain': True,
        'cluster': 'school_year,fund_code'
    },
    "item_dict": {
        'is_domain': True,
        'cluster': 'school_year,item_code'
    },
    "object": {
        'is_domain': True,
        'cluster': 'school_year,object_code'
    },
    "program": {
        'is_domain': True,
        'cluster': 'school_year,program_code'
    },
    "revenue": {
        'is_domain': True,
        'cluster': 'school_year,revenue_code'
    },

    # Line items
    "all_districts": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,year,is_forecast'
    },
    "capital_project_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code'
    },
    "debt_service_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code'
    },
    "general_fund_expenditures": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,object_code,activity_code'
    },
    "general_fund_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code'
    },
    "item_numbers": {
        'is_domain': False,
        'cluster': 'school_year,item_code,fund_code'
    },
    "trans_vehicle_revenues": {
        'is_domain': False,
        'cluster': 'school_year,ccddd,fund_code,revenue_code'
    }
}

YEARS = [
    "2015-2016",
    "2016-2017",
    "2017-2018",
    "2018-2019",
    "2019-2020",
    "2020-2021",
    "2021-2022",
    "2022-2023",
    "2023-2024",
    "2024-2025",
]

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


def make_query(tablename, info, safs_type):
    uri_list = [SAFS_TEMPL.format(year=year,
                                  tablename=tablename,
                                  safs_type=safs_type,
                                  root=GS_SAFS_ROOT)
                for year in YEARS]
    if info["is_domain"]:
        bq_tablename = f'{safs_type}_d_{tablename}'
    else:
        bq_tablename = f'{safs_type}_{tablename}'
    return LOAD_QUERY_TEMPLATE.format(
        tablename=bq_tablename,
        cluster=info["cluster"],
        uri_list=uri_list)


def load_table(tablename, info, safs_type):
    query = make_query(tablename, info, safs_type)
    print("query: ", query)
    query_job = client.query(query)  # API request
    rows = query_job.result()  # Waits for query to finish
    print("results: ")
    for row in rows:
        print("row name: ", row.name)


def main():
    for tablename, info in TABLE_INFO.items():
        load_table(tablename, info, 'f195')


main()
