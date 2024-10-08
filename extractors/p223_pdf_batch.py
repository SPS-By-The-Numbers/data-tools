"""
Extracts data from batches of P223 PDFs from seattleschools.org.
Reads PDFs from an input directory and writes CSVs to an output directory
$ python3 p223_batch.py path/to/input/directory path/to/output/directory

The input directory should contain PDFs similar to https://www.seattleschools.org/wp-content/uploads/2024/09/P223_Sep24.pdf,
and the PDF file names are expected to follow the naming convention to identify their month and year.
"""

import glob
import os
import re
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import p223_pdf_to_csv


def month_from_pdf_file_name(pdf_path) -> str:
    filename = os.path.basename(pdf_path)

    m = re.match(r'^P223_(\D+)(\d+)\.pdf$', filename)
    if m is None:
        raise Exception(f"Unable to determine month and year from filename: '{filename}'")

    month_name_abbreviated = m.group(1)
    year_two_digit = m.group(2)

    parsed_month = time.strptime(f'{month_name_abbreviated} {year_two_digit}', '%b %y')
    month = time.strftime('%Y-%m', parsed_month)

    return month


def main(input_directory, output_directory):
    pdftotext = shutil.which('pdftotext')
    if pdftotext is None:
        sys.exit("'pdftotext' is not installed. See installation instructions in README.md.")

    tr = shutil.which('tr')
    if tr is None:
        sys.exit("'tr' is not installed. See installation instructions in README.md.")

    pdf_paths = glob.glob(f'{input_directory}/*.pdf')

    month_csv_paths = []

    for pdf_path in pdf_paths:
        with tempfile.NamedTemporaryFile(delete_on_close=False) as squished_tempfile:
            # '-f 2' to start processing on the second page of the PDF (since page 1 is a cover page).
            pdftotext_process = subprocess.Popen([pdftotext, '-layout', pdf_path, '-f', '2', '-'], stdout=subprocess.PIPE)
            tr_process = subprocess.Popen([tr, '-s', "' '"], stdin=pdftotext_process.stdout, stdout=squished_tempfile)
            pdftotext_process.stdout.close()
            out, err = tr_process.communicate()

            if err is not None:
                sys.exit(f"'pdftotext' and/or 'tr' had an error:\n{err}")

            if out is not None:
                print(f"'pdftotext' and/or 'tr' produced output on stdout, which was unexpected:\n{out}")

            squished_tempfile.close()

            month = month_from_pdf_file_name(pdf_path)
            month_csv_file_path = f'{output_directory}/month/{month}.csv'
            pathlib.Path(os.path.dirname(month_csv_file_path)).mkdir(parents=True, exist_ok=True)

            p223_pdf_to_csv.main(squished_tempfile.name, month_csv_file_path, month)

            print(f"Extracted {pdf_path} to {month_csv_file_path}")

            month_csv_paths.append((month, month_csv_file_path))

    month_csv_paths.sort(key=lambda month_and_path: month_and_path[0])

    # Concatenate all the CSVs into one.
    all_csv_path = f'{output_directory}/all.csv'
    pathlib.Path(os.path.dirname(all_csv_path)).mkdir(parents=True, exist_ok=True)

    with open(all_csv_path, 'w') as all_csv:
        first_month_csv = True

        for (_, month_csv_file_path) in month_csv_paths:
            with open(month_csv_file_path, 'r', encoding='utf-8') as month_csv_file:
                header_line = month_csv_file.readline()
                if first_month_csv:
                    all_csv.write(header_line)
                    first_month_csv = False

                for data_line in month_csv_file:
                    all_csv.write(data_line)

    print(f"Concatenated all extracted CSVs to {all_csv_path}")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
