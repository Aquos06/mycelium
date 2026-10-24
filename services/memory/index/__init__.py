"""The index: a searchable copy of the vault. Only the indexer writes it; drop it and re-run to rebuild.

base.py       the Index protocol and the fuzzy threshold
inmemory.py   InMemoryIndex for unit tests, with a pure-Python pg_trgm look-alike so fuzzy matching behaves the same
tables.py     the index tables as SQLAlchemy Core objects, bound to one schema
postgres.py   PostgresIndex over the async engine; ensure_schema() runs ../migrations/ (Alembic) into its schema
"""

from .base import FUZZY_THRESHOLD, Index
from .inmemory import InMemoryIndex, trigram_similarity
from .postgres import MIGRATIONS, PostgresIndex

__all__ = ["FUZZY_THRESHOLD", "MIGRATIONS", "Index", "InMemoryIndex", "PostgresIndex", "trigram_similarity"]
