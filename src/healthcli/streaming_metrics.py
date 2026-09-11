"""Incremental metric aggregation across chunks, without retaining raw rows.

`missing_summary` in `quality.py` needs the full DataFrame because it calls
`df.isna().sum()` once. `StreamingMetricAggregator` reaches the same result
by adding each chunk's per-column missing/total counts as it arrives, so the
running totals -- not the rows themselves -- are the only state carried
between chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, cast

import pandas as pd


@dataclass
class StreamingMetricAggregator:
    """Accumulates row counts and per-column missing-value counts across chunks."""

    total_rows: int = 0
    _missing_counts: Dict[str, int] = field(default_factory=dict)
    _column_order: list = field(default_factory=list)

    def add_chunk(self, chunk: pd.DataFrame) -> None:
        self.total_rows += len(chunk)
        missing = chunk.isna().sum()
        for column, count in missing.items():
            if column not in self._missing_counts:
                self._missing_counts[column] = 0
                self._column_order.append(column)
            self._missing_counts[column] += int(count)

    def missing_summary(self) -> pd.DataFrame:
        """Return the same shape as `quality.missing_summary`'s DataFrame."""
        if not self._column_order:
            return pd.DataFrame(columns=["missing_count", "missing_ratio"])

        counts = [self._missing_counts[c] for c in self._column_order]
        ratios = [c / self.total_rows if self.total_rows else 0.0 for c in counts]
        return cast(
            pd.DataFrame,
            pd.DataFrame(
                {"missing_count": counts, "missing_ratio": ratios},
                index=pd.Index(self._column_order, name=None),
            ).sort_values("missing_ratio", ascending=False),
        )
