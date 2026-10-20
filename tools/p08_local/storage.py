"""Own the lifetime of each independent SQLite inspection connection."""
from contextlib import closing, contextmanager
import sqlite3


@contextmanager
def inspect_database(profile):
    # Connection.__exit__ ends a transaction; closing also releases the OS handle.
    with closing(sqlite3.connect(profile / 'offline.sqlite3')) as database:
        yield database
