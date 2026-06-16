"""Parallel-extract helper for the fiscal corpus.

Each per-doc-kind `extract_*.py` driver wires a parse function + filename
predicate into `run_extract`, which handles:
  - Walking the input directory
  - Spawning a multiprocessing.Pool of workers
  - Consuming results as they arrive and writing them to CSV / JSON / summary
  - Error tracking

Workers run a top-level function (`_worker`) that the pool can pickle.
"""

import argparse
import csv
import json
import logging
import multiprocessing as mp
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

from .filename import parse as parse_filename


logger = logging.getLogger(__name__)


# Module-level state for worker processes: set once per worker via the
# Pool initializer. Holds the parse function the main script wants invoked
# (a top-level callable so multiprocessing can pickle it by name).
_WORKER_PARSE_FN: Callable = None


def _worker_init(parse_fn_module: str, parse_fn_name: str):
    """Pool initializer -- import the parse function in each worker."""
    global _WORKER_PARSE_FN
    mod = __import__(parse_fn_module, fromlist=[parse_fn_name])
    _WORKER_PARSE_FN = getattr(mod, parse_fn_name)


def _worker(path_str: str):
    """Parse one PDF and return (path, error, rows)."""
    path = Path(path_str)
    try:
        info = parse_filename(path)
    except ValueError as e:
        return (path_str, f"filename: {e}", [])
    try:
        rows = list(_WORKER_PARSE_FN(info))
    except Exception as e:  # noqa: BLE001 -- keep the corpus run going
        return (path_str, f"parse: {type(e).__name__}: {e}", [])
    return (path_str, None, rows)


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(repr(o))


def run_extract(
    parse_fn_module: str,
    parse_fn_name: str,
    fieldnames: list,
    walker: Callable[[Path], Iterable[Path]],
    description: str = "",
):
    """Top-level CLI driver. Caller passes:
      - parse_fn_module, parse_fn_name: dotted name of the parser to invoke in workers
      - fieldnames: CSV column order
      - walker: function (root_path) -> iterable of PDF paths to process
    """
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("input", help="corpus root dir or single PDF")
    ap.add_argument("--format", choices=("csv", "json", "summary"), default="csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 1) - 1),
                    help="parallel worker processes (default: ncpu-1)")
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level)

    files = list(walker(Path(args.input)))
    if args.limit:
        files = files[: args.limit]
    total = len(files)
    if total == 0:
        print("[done] files parsed: 0, errors: 0, total rows: 0", file=sys.stderr)
        return

    writer = None
    total_rows = 0
    parsed = 0
    errors = 0

    if args.workers > 1 and len(files) > 1:
        ctx = mp.get_context("fork")
        pool = ctx.Pool(
            processes=args.workers,
            initializer=_worker_init,
            initargs=(parse_fn_module, parse_fn_name),
        )
        results = pool.imap_unordered(_worker, [str(p) for p in files], chunksize=4)
    else:
        # Single-process mode: still go through the same worker function so
        # we don't maintain two parsing code paths.
        _worker_init(parse_fn_module, parse_fn_name)
        results = (_worker(str(p)) for p in files)
        pool = None

    try:
        for path_str, err, rows in results:
            name = Path(path_str).name
            if err is not None:
                logger.error("%s: %s", path_str, err)
                errors += 1
                continue
            if args.format == "summary":
                print(f"{len(rows):5d}  {name}")
            elif args.format == "json":
                for r in rows:
                    print(json.dumps(r, default=_json_default))
            else:
                if writer is None:
                    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
                    writer.writeheader()
                for r in rows:
                    writer.writerow({k: (str(v) if isinstance(v, Decimal) else v)
                                     for k, v in r.items()})
            total_rows += len(rows)
            parsed += 1
            if parsed % 200 == 0:
                print(f"  ... {parsed}/{total} files, {total_rows:,} rows",
                      file=sys.stderr)
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    print(f"[done] files parsed: {parsed}, errors: {errors}, total rows: {total_rows}",
          file=sys.stderr)
