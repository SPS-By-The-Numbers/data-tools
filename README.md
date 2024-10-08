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

