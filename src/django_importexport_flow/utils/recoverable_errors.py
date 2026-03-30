"""Exception groups for expected tabular import/export failures (CLI and admin)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import DatabaseError

try:
    from pandas.errors import EmptyDataError, ParserError

    _PANDAS_TABULAR = (ParserError, EmptyDataError)
except ImportError:
    _PANDAS_TABULAR = ()

# Engine / I/O / ORM issues we surface as a user-facing message (not a 500).
TABULAR_ENGINE_RECOVERABLE: tuple[type[BaseException], ...] = (
    ValidationError,
    ValueError,
    TypeError,
    OSError,
    DatabaseError,
) + _PANDAS_TABULAR
