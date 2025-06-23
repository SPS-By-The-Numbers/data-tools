This directory contains code for reading in the OSPI SAFS data files
into avro format.

There are 4 types of files
 1. `{dataset}_{format}_to_avro.py` - Conversion of a file to an avro normalizing column names.
 2. `{dataset}_load_data.py` - Pulls results of the converted AVRO files into a RDMBS.
 3. `{dataset}_calculate_fields.py` - Merges records, infers fields, does extra calculations, etc.
 4.  `{dataset}_dump_tables.py` - Dumps the RDMBS into avro files. This produces the "final" result.

Three datasets are supproted:
  * f195 - Budget
  * f196 - Actuals
  * s275 - Personnel files

For the f195 and f196, the pipeline is fairly straight forward with
most of the work occurring in step (1) -- normalizing column names.

The s275 is an entirely different beast. The datamodel of the published
dataset is a mashup of denormalized rows and values with different
update periods pooling from different departments. A very large amount
of work happens in steps 2. and 3. to normalize the data and then
attempt to figure out how to correctly interpret it in useful ways.
