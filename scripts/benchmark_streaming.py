"""Benchmark streaming vs. materialized pipeline processing on a 1M-row dataset.

Generates a synthetic clinical-shaped CSV (no real patient data), then runs
`process_chunks` (materialized, `pd.concat`-based) and `process_chunks_streaming`
(Parquet sink, no concat) against it, reporting wall-clock runtime, peak
resident memory, and rows/second for each so the two modes can be compared
on the same input.

Usage:
    python scripts/benchmark_streaming.py [--rows 1000000] [--chunk-size 50000]

Peak memory is sampled via OS-level RSS (`psutil`) on a lightweight polling
thread, not `tracemalloc`: `tracemalloc`'s per-allocation bookkeeping adds
enough overhead to a workload built from millions of individual Pydantic
model instantiations (the FHIR validation step) to turn a ~2-minute run into
a multi-hour one, and it under-represents pandas/pyarrow's C-level buffers
in any case. RSS is what actually matters for capacity planning.
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from healthcli.pipeline import process_chunks, process_chunks_streaming  # noqa: E402
from healthcli.sinks import ParquetSink  # noqa: E402

try:
    import psutil

    _PROCESS = psutil.Process()
except ImportError:
    psutil = None
    _PROCESS = None

GENDERS = ["Male", "Female"]
GLU_RESULTS = ["None", "Norm", ">200", ">300"]


@dataclass(frozen=True)
class BenchmarkResult:
    mode: str
    rows: int
    runtime_seconds: float
    peak_rss_mb: Optional[float]

    @property
    def rows_per_second(self) -> float:
        return self.rows / self.runtime_seconds if self.runtime_seconds > 0 else float("inf")

    def report(self) -> str:
        rss = f"{self.peak_rss_mb:.1f} MB" if self.peak_rss_mb is not None else "n/a (psutil not installed)"
        return (
            f"[{self.mode}] rows={self.rows:,} runtime={self.runtime_seconds:.2f}s "
            f"rows/sec={self.rows_per_second:,.0f} peak_rss={rss}"
        )


class _PeakRssSampler:
    """Polls RSS on a background thread and tracks the maximum observed value."""

    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self.peak_mb: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "_PeakRssSampler":
        if _PROCESS is None:
            return self
        self.peak_mb = _PROCESS.memory_info().rss / (1024 * 1024)
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def _poll(self) -> None:
        while not self._stop.is_set():
            rss_mb = _PROCESS.memory_info().rss / (1024 * 1024)
            if self.peak_mb is None or rss_mb > self.peak_mb:
                self.peak_mb = rss_mb
            self._stop.wait(self.interval_seconds)

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def generate_synthetic_csv(path: Path, rows: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["patient_nbr", "gender", "age", "max_glu_serum", "A1Cresult", "change", "diabetesMed"])
        for i in range(rows):
            writer.writerow(
                [
                    100000 + i,
                    rng.choice(GENDERS),
                    rng.randint(0, 99),
                    rng.choice(GLU_RESULTS),
                    rng.choice(["None", "Norm", ">7", ">8"]),
                    rng.choice(["No", "Ch"]),
                    rng.choice(["Yes", "No"]),
                ]
            )


def run_materialized(csv_path: Path, chunk_size: int, logger: logging.Logger) -> BenchmarkResult:
    with _PeakRssSampler() as sampler:
        start = time.perf_counter()
        df, _metrics, _fhir = process_chunks(str(csv_path), chunk_size, logger)
        elapsed = time.perf_counter() - start
    return BenchmarkResult(
        mode="materialized (pd.concat)",
        rows=len(df),
        runtime_seconds=elapsed,
        peak_rss_mb=sampler.peak_mb,
    )


def run_streaming(csv_path: Path, chunk_size: int, output_path: Path, logger: logging.Logger) -> BenchmarkResult:
    sink = ParquetSink(str(output_path))
    with _PeakRssSampler() as sampler:
        start = time.perf_counter()
        _metrics, _fhir, _aggregator, total_rows = process_chunks_streaming(str(csv_path), chunk_size, logger, sink)
        elapsed = time.perf_counter() - start
    return BenchmarkResult(
        mode="streaming (Parquet sink)",
        rows=total_rows,
        runtime_seconds=elapsed,
        peak_rss_mb=sampler.peak_mb,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--chunk-size", type=int, default=50_000)
    parser.add_argument("--keep-files", action="store_true", help="Keep generated CSV/Parquet after the run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("benchmark")

    if psutil is None:
        print("Warning: psutil is not installed; peak RSS will be reported as n/a. `pip install psutil` to enable it.")

    work_dir = Path(__file__).resolve().parent.parent / "output" / "benchmark"
    work_dir.mkdir(parents=True, exist_ok=True)
    csv_path = work_dir / f"synthetic_{args.rows}.csv"
    parquet_path = work_dir / f"synthetic_{args.rows}.parquet"

    if not csv_path.exists():
        print(f"Generating synthetic dataset: {args.rows:,} rows -> {csv_path}")
        generate_synthetic_csv(csv_path, args.rows)

    print(f"\nBenchmarking with chunk_size={args.chunk_size:,}\n")

    materialized = run_materialized(csv_path, args.chunk_size, logger)
    print(materialized.report())

    streaming = run_streaming(csv_path, args.chunk_size, parquet_path, logger)
    print(streaming.report())

    if materialized.peak_rss_mb and streaming.peak_rss_mb:
        delta_pct = (1 - streaming.peak_rss_mb / materialized.peak_rss_mb) * 100
        print(f"\nPeak RSS: streaming mode used {delta_pct:.1f}% {'less' if delta_pct >= 0 else 'more'} memory")

    if not args.keep_files:
        csv_path.unlink(missing_ok=True)
        parquet_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
