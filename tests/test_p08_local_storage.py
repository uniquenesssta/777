"""Real SQLite lifetime checks; Windows deletion is not simulated on other OSes."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.p08_local.storage import inspect_database


class LocalInspectionTests(unittest.TestCase):
    def test_successful_inspection_closes_the_connection_before_directory_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            database = None
            try:
                with inspect_database(profile) as database:
                    self.assertEqual(database.execute('SELECT 17').fetchone(), (17,))
                with self.assertRaises(sqlite3.ProgrammingError):
                    database.execute('SELECT 1')
            finally:
                if database is not None:
                    database.close()

    def test_reader_failure_is_preserved_and_the_connection_is_closed(self):
        class ReadFailure(Exception):
            pass

        with tempfile.TemporaryDirectory() as folder:
            database = None
            try:
                with self.assertRaisesRegex(ReadFailure, 'original read failure'):
                    with inspect_database(Path(folder)) as database:
                        database.execute('SELECT 23').fetchone()
                        raise ReadFailure('original read failure')
                with self.assertRaises(sqlite3.ProgrammingError):
                    database.execute('SELECT 1')
            finally:
                if database is not None:
                    database.close()


if __name__ == '__main__':
    unittest.main()
