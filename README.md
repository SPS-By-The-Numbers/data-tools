# data-tools
Scripts and tools for ingesting data.

## Two data paths: SAFS raw vs Fiscal PDF

OSPI publishes the same district financial data twice — once as raw
Microsoft Access `.accdb`/`.mdb` files (the **SAFS raw** path,
extracted by [`extractors/safs/`](extractors/safs/)) and once as
printed PDFs (the **Fiscal PDF** path, extracted by
[`extractors/fiscal/`](extractors/fiscal/)). Both extractors run in
this repo, but they capture **different slices** of the underlying
data.

**Short version:**
- For top-level per-item / per-account / per-program-activity-object
  totals, prefer the SAFS raw path — faster, more stable.
- For salary/staff detail, balance sheets, mid-year Final Budget
  revisions, indirect rate calculations, and ~15 other dimensions that
  only appear on the printed forms, use the Fiscal PDF path.
- For per-school granularity, only SAFS raw's
  `ActualsChildGenerlFundExpenditures` has it.

See [extractors/fiscal/DATA_SOURCE_DIVERGENCE.md](extractors/fiscal/DATA_SOURCE_DIVERGENCE.md)
for the complete per-dimension mapping between the two paths,
recommendations for which to use when, and a plan for closing the
remaining SAFS `ITEMDIC` coverage gap.

For the fiscal PDF outputs specifically, start with
[extractors/fiscal/OVERVIEW.md](extractors/fiscal/OVERVIEW.md) (map
of every fact CSV) and
[extractors/fiscal/CSV_GUIDE.md](extractors/fiscal/CSV_GUIDE.md)
(per-table schema, join keys, quirks).

## P223 data

### Setup

**Note:** This has only been tested on macOS.

```console
$ brew install pdftotext
```

`tr` is also required, but `tr` should already be installed by the OS:

```console
$ which tr
/usr/bin/tr
```

### Extracting data from multiple P223 PDFs
To extract data from multiple PDFs in an input directory:

```console
$ python3 extractors/p223_pdf_batch.py my/input/directory my/output/directory
```

**TODO:** Add instructions for retrieving PDFs and cached outputs from Google Cloud.

### Extracting data from a single P223 PDF
```console
$ curl \
    https://www.seattleschools.org/wp-content/uploads/2024/09/P223_Sep24.pdf \
    -o p223_sep24.pdf
$ pdftotext -layout p223_sep24.pdf -f 2 - | tr -s ' ' > squished.txt
$ python3 extractors/p223_pdf_to_csv.py squished.txt out.csv
```

### Data types and formats
Decimals are prefered to IEEE floating points. Many codes and IDs lend
themselves to integers.  In the accounting system, "Activity" and "Program" in
particular look like integers. However, in inte S275 document they added two
character values "SB" and "CP" to represent ASB and Capital Projects Fund
assignments even though those are not officially part of the Activity and
Program domains.  For these situations, we will use a custom encoding of the
non-confirmant values ot map into an unused portion of the integer space
(typically negatives) to allow the schema to be integers.

We will use BigQuery Decimal defaults of precision=38 and scale=9.

Monetary values more standardly use precision=19 and scale=2, but to keep
everything uniform just using BQ's larger range.
