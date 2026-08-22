"""Memory-efficient pandas transformations for clinical data pipelines."""

from dataclasses import dataclass
import logging
from typing import Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class MemoryOptimizationMetrics:
    """Measurements produced by one optimization pass."""

    before_bytes: int
    after_bytes: int
    numeric_columns: int
    categorical_columns: int

    @property
    def saved_bytes(self) -> int:
        return max(self.before_bytes - self.after_bytes, 0)

    @property
    def reduction_ratio(self) -> float:
        if self.before_bytes == 0:
            return 0.0
        return self.saved_bytes / self.before_bytes


class PandasMemoryOptimizer:
    """Downcast numeric columns and dictionary-encode low-cardinality strings.

    The optimizer returns a copy by default so callers can preserve an input
    frame for audit or comparison. A conversion is retained only when it
    reduces the deep memory footprint of that column.
    """

    def __init__(
        self,
        category_threshold: float = 0.5,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if not 0.0 < category_threshold <= 1.0:
            raise ValueError("category_threshold must be in the range (0, 1]")
        self.category_threshold = category_threshold
        self.logger = logger or logging.getLogger(__name__)

    def optimize(self, frame: pd.DataFrame) -> Tuple[pd.DataFrame, MemoryOptimizationMetrics]:
        """Return an optimized frame and measurements for the transformation."""
        optimized = frame.copy()
        before_bytes = int(optimized.memory_usage(index=True, deep=True).sum())
        numeric_columns = 0
        categorical_columns = 0

        for column in optimized.columns:
            series = optimized[column]
            if pd.api.types.is_integer_dtype(series):
                candidate = pd.to_numeric(series, downcast="integer")
                numeric_columns += int(str(candidate.dtype) != str(series.dtype))
                optimized[column] = candidate
            elif pd.api.types.is_float_dtype(series):
                candidate = pd.to_numeric(series, downcast="float")
                numeric_columns += int(str(candidate.dtype) != str(series.dtype))
                optimized[column] = candidate
            elif pd.api.types.is_object_dtype(series) and len(series) > 0:
                non_null = series.dropna()
                cardinality = non_null.nunique()
                ratio = cardinality / max(len(non_null), 1)
                if ratio <= self.category_threshold:
                    candidate = series.astype("category")
                    current_size = int(series.memory_usage(deep=True))
                    candidate_size = int(candidate.memory_usage(deep=True))
                    if candidate_size < current_size:
                        optimized[column] = candidate
                        categorical_columns += 1

        after_bytes = int(optimized.memory_usage(index=True, deep=True).sum())
        metrics = MemoryOptimizationMetrics(
            before_bytes=before_bytes,
            after_bytes=after_bytes,
            numeric_columns=numeric_columns,
            categorical_columns=categorical_columns,
        )
        self.logger.info(
            "memory optimization completed: before_bytes=%d after_bytes=%d reduction_ratio=%.3f",
            metrics.before_bytes,
            metrics.after_bytes,
            metrics.reduction_ratio,
        )
        return optimized, metrics
