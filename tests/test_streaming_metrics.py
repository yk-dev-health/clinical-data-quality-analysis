import pandas as pd
import pytest

from healthcli.streaming_metrics import StreamingMetricAggregator


def test_aggregator_accumulates_row_counts_across_chunks():
    aggregator = StreamingMetricAggregator()
    aggregator.add_chunk(pd.DataFrame({"a": [1, 2, None]}))
    aggregator.add_chunk(pd.DataFrame({"a": [4, None]}))
    assert aggregator.total_rows == 5


def test_aggregator_missing_summary_matches_full_frame_equivalent():
    chunk1 = pd.DataFrame({"a": [1, None, 3], "b": [None, None, "x"]})
    chunk2 = pd.DataFrame({"a": [None, 5], "b": ["y", "z"]})

    aggregator = StreamingMetricAggregator()
    aggregator.add_chunk(chunk1)
    aggregator.add_chunk(chunk2)
    streamed = aggregator.missing_summary()

    full = pd.concat([chunk1, chunk2], ignore_index=True)
    full_missing = full.isna().sum()
    full_ratio = full_missing / len(full)

    for column in ["a", "b"]:
        assert streamed.loc[column, "missing_count"] == full_missing[column]
        assert streamed.loc[column, "missing_ratio"] == pytest.approx(full_ratio[column])


def test_empty_aggregator_returns_empty_summary():
    aggregator = StreamingMetricAggregator()
    summary = aggregator.missing_summary()
    assert summary.empty
