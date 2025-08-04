import os

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as postgres_insert


class DbConnection:
    """Simple abstraction for connecting to the database.

    Currently only supports postgresql but you could support others if the
    queries were updated to handle dialect variantions.
    """
    def __init__(self, args):
        self._insert = postgres_insert
        self._engine = create_engine(
            (f"postgresql+psycopg2://{args.db_user}:{args.db_password}"
                f"@localhost/{args.db_name}"),
            echo=False).execution_options(autocommit=False)

    @property
    def insert(self):
        return self._insert

    @property
    def engine(self):
        return self._engine


def add_db_arguments(parser):
    parser.add_argument('--db-name', default="scratch",
                        help='Database to connect to. Ignored in sqlite')
    parser.add_argument('--db-user', default=os.getlogin(),
                        help='User to connect as. Ignored in sqlite')
    parser.add_argument('--db-password', default="",
                        help='Password to connect with. Ignored in sqlite')
