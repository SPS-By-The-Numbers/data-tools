import os

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


class DbConnection:
    """Simple abstraction for connecting to different databases"""
    def __init__(self, args):
        if args.engine == 'sqlite':
            self._insert = sqlite_insert
            self._engine = create_engine(
                "sqlite://", echo=False).execution_options(autocommit=False)
        else:
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
    parser.add_argument('--engine', default="sqlite",
                        choices=['sqlite', 'postgresql'],
                        help='Which database backend to use')
    parser.add_argument('--db-name', default="scratch",
                        help='Database to connect to. Ignored in sqlite')
    parser.add_argument('--db-user', default=os.getlogin(),
                        help='User to connect as. Ignored in sqlite')
    parser.add_argument('--db-password', default="",
                        help='Password to connect with. Ignored in sqlite')
