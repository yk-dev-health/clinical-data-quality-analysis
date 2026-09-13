import numpy as np
import pandas as pd

from healthcli.idempotency import (
    IdempotencyChecker,
    ProcessingManifest,
    RunIdentity,
    compute_dataset_hash,
    compute_row_hash,
    compute_row_hashes,
)


def test_dataset_hash_is_deterministic_for_same_content(tmp_path):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("patient_nbr,age\n1,45\n")
    file2.write_text("patient_nbr,age\n1,45\n")
    assert compute_dataset_hash(str(file1)) == compute_dataset_hash(str(file2))


def test_dataset_hash_changes_with_content(tmp_path):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("patient_nbr,age\n1,45\n")
    file2.write_text("patient_nbr,age\n1,46\n")
    assert compute_dataset_hash(str(file1)) != compute_dataset_hash(str(file2))


def test_run_id_changes_when_pipeline_version_changes():
    identity_v1 = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="1.0.0")
    identity_v2 = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="2.0.0")
    assert identity_v1.run_id != identity_v2.run_id


def test_run_id_changes_when_schema_version_changes():
    identity_v1 = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="1.0.0")
    identity_v2 = RunIdentity(dataset_hash="abc", schema_version="2.0", pipeline_version="1.0.0")
    assert identity_v1.run_id != identity_v2.run_id


def test_row_hash_is_order_independent_across_columns():
    row1 = pd.Series({"a": "X", "b": "Y"})
    row2 = pd.Series({"b": "Y", "a": "X"})
    assert compute_row_hash(row1, ["a", "b"]) == compute_row_hash(row2, ["a", "b"])


def test_row_hash_normalizes_whitespace_and_case():
    row1 = pd.Series({"gender": "Male"})
    row2 = pd.Series({"gender": " male "})
    assert compute_row_hash(row1, ["gender"]) == compute_row_hash(row2, ["gender"])


def test_row_hash_differs_for_different_values():
    row1 = pd.Series({"age": 45})
    row2 = pd.Series({"age": 46})
    assert compute_row_hash(row1, ["age"]) != compute_row_hash(row2, ["age"])


def test_row_hash_is_not_reversible_to_raw_value():
    row = pd.Series({"patient_nbr": "12345678"})
    digest = compute_row_hash(row, ["patient_nbr"])
    assert "12345678" not in digest


def test_vectorized_row_hashes_match_per_row_hash():
    """`compute_row_hashes` (used on whole chunks) must agree with the
    per-row `compute_row_hash` it replaced -- otherwise a manifest built
    under the old code would stop recognising rows as duplicates."""
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2", "3"],
            "gender": [" Male", "female ", None],
            "age": [45.0, np.nan, 60.0],
        }
    )
    columns = ["patient_nbr", "gender", "age"]

    expected = df.apply(lambda row: compute_row_hash(row, columns), axis=1).reset_index(drop=True)
    actual = compute_row_hashes(df, columns).reset_index(drop=True)

    assert (expected == actual).all()


def test_vectorized_row_hashes_match_per_row_hash_for_categorical_columns():
    """Memory-optimized DataFrames store low-cardinality text columns as
    `category` dtype; the vectorized hashing must not confuse a category's
    label set with the actual per-row values (see fhir/idempotency fix)."""
    df = pd.DataFrame({"gender": pd.Categorical(["Male", "Female", "Male"]), "age": [10, 20, 30]})
    columns = ["gender", "age"]

    expected = df.apply(lambda row: compute_row_hash(row, columns), axis=1).reset_index(drop=True)
    actual = compute_row_hashes(df, columns).reset_index(drop=True)

    assert (expected == actual).all()


def test_manifest_persists_and_reloads(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest = ProcessingManifest(str(manifest_path))
    manifest.record("run1", ["hash_a", "hash_b"])
    manifest.save()

    reloaded = ProcessingManifest(str(manifest_path))
    assert reloaded.processed_hashes("run1") == {"hash_a", "hash_b"}


def test_manifest_separates_hashes_by_run_id(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest = ProcessingManifest(str(manifest_path))
    manifest.record("run1", ["hash_a"])
    manifest.record("run2", ["hash_b"])
    manifest.save()

    assert manifest.processed_hashes("run1") == {"hash_a"}
    assert manifest.processed_hashes("run2") == {"hash_b"}


def test_checker_flags_all_rows_new_on_first_run(tmp_path):
    manifest = ProcessingManifest(str(tmp_path / "manifest.json"))
    identity = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="1.0.0")
    checker = IdempotencyChecker(manifest, identity, hash_columns=["patient_nbr", "age"])

    df = pd.DataFrame({"patient_nbr": ["1", "2"], "age": [45, 60]})
    result = checker.process_chunk(df)

    assert len(result) == 2
    assert checker.metrics.new_rows == 2
    assert checker.metrics.duplicate_rows == 0


def test_checker_detects_duplicates_on_second_run(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    identity = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="1.0.0")

    df = pd.DataFrame({"patient_nbr": ["1", "2"], "age": [45, 60]})

    manifest1 = ProcessingManifest(str(manifest_path))
    checker1 = IdempotencyChecker(manifest1, identity, hash_columns=["patient_nbr", "age"])
    checker1.process_chunk(df)
    checker1.commit()

    manifest2 = ProcessingManifest(str(manifest_path))
    checker2 = IdempotencyChecker(manifest2, identity, hash_columns=["patient_nbr", "age"])
    result = checker2.process_chunk(df)

    assert len(result) == 0
    assert checker2.metrics.duplicate_rows == 2
    assert checker2.metrics.new_rows == 0


def test_checker_treats_different_pipeline_version_as_new(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    df = pd.DataFrame({"patient_nbr": ["1"], "age": [45]})

    identity_v1 = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="1.0.0")
    manifest1 = ProcessingManifest(str(manifest_path))
    checker1 = IdempotencyChecker(manifest1, identity_v1, hash_columns=["patient_nbr", "age"])
    checker1.process_chunk(df)
    checker1.commit()

    identity_v2 = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="2.0.0")
    manifest2 = ProcessingManifest(str(manifest_path))
    checker2 = IdempotencyChecker(manifest2, identity_v2, hash_columns=["patient_nbr", "age"])
    result = checker2.process_chunk(df)

    assert len(result) == 1
    assert checker2.metrics.new_rows == 1


def test_checker_handles_partial_duplicates_within_chunk(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    identity = RunIdentity(dataset_hash="abc", schema_version="1.0", pipeline_version="1.0.0")

    df1 = pd.DataFrame({"patient_nbr": ["1", "2"], "age": [45, 60]})
    manifest1 = ProcessingManifest(str(manifest_path))
    checker1 = IdempotencyChecker(manifest1, identity, hash_columns=["patient_nbr", "age"])
    checker1.process_chunk(df1)
    checker1.commit()

    df2 = pd.DataFrame({"patient_nbr": ["2", "3"], "age": [60, 70]})
    manifest2 = ProcessingManifest(str(manifest_path))
    checker2 = IdempotencyChecker(manifest2, identity, hash_columns=["patient_nbr", "age"])
    result = checker2.process_chunk(df2)

    assert len(result) == 1
    assert result.iloc[0]["patient_nbr"] == "3"
    assert checker2.metrics.duplicate_rows == 1
    assert checker2.metrics.new_rows == 1
