# data-tools
Scripts and tools for ingesting data.

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
