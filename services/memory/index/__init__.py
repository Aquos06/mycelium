"""The index: a searchable copy of the vault. Only the indexer writes it; drop it and re-run to rebuild.

base.py       the Index protocol and the fuzzy threshold
inmemory.py   InMemoryIndex for unit tests, with a pure-Python pg_trgm look-alike so fuzzy matching behaves the same
postgres.py   PostgresIndex (asyncpg), schema.sql next to it
"""

from .base import FUZZY_THRESHOLD, Index
from .inmemory import InMemoryIndex, trigram_similarity
from .postgres import PostgresIndex

__all__ = ["FUZZY_THRESHOLD", "Index", "InMemoryIndex", "PostgresIndex", "trigram_similarity"]
