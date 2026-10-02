"""Bounded multi-row INSERTs for the index's parameter-only VALUES statements."""
from itertools import islice
import re
import sqlite3


def execute_insert_batches(cursor, sql, rows):
    """Keep the caller's transaction/conflict policy and input row order.

    Multi-row statements amortize SQLite's per-statement trigger setup. This
    helper only accepts a single VALUES tuple made entirely of placeholders;
    it never rewrites arbitrary expressions or binds identifiers from input.
    """
    match = re.search(r'\bVALUES\s*(\(\s*\?(?:\s*,\s*\?)*\s*\))',sql,re.IGNORECASE)
    if match is None or not sql.lstrip().upper().startswith('INSERT'):
        raise ValueError('Expected an INSERT with a parameter-only VALUES tuple')
    prefix, values, suffix = sql[:match.start(1)],match.group(1),sql[match.end(1):]
    if '?' in prefix or '?' in suffix:
        raise ValueError('Parameters outside VALUES are not supported')
    width = values.count('?')
    limit = cursor.connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    batch_size = min(500,limit//width)
    if batch_size < 1:
        raise ValueError('One INSERT row exceeds the SQLite parameter limit')
    iterator = iter(rows)
    affected = 0
    while batch := list(islice(iterator,batch_size)):
        if any(len(row) != width for row in batch):
            raise ValueError('INSERT row has an unexpected number of values')
        statement = prefix + ','.join([values]*len(batch)) + suffix
        cursor.execute(statement,tuple(value for row in batch for value in row))
        affected += max(0,cursor.rowcount)
    return affected
