# tools

Ad-hoc analysis/CLI scripts that operate on pipeline outputs (CSV/AVRO). Not
part of the production ETL pipeline — no promises on stability or paths.

Some scripts reference input CSVs by root-relative name; those inputs may now
live in `attic/` after the repo reorg. Fix paths on next use, don't chase them
now.
