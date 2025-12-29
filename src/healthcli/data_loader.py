from pathlib import Path
import pandas as pd


def load_csv_data(data_path: str) -> pd.DataFrame:
    """
    Load a clinical tabular dataset from a CSV file.

    This function is intentionally minimal:
    - It only loads the data
    - It performs basic validation (file existence, readability)
    - No cleaning, filtering, or imputation is applied here

    Parameters
    ----------
    data_path : str
        Path to the clinical CSV dataset.

    Returns
    -------
    pd.DataFrame
        Loaded dataset as a pandas DataFrame.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file is empty or cannot be parsed as CSV.
    """
    path = Path(data_path)

    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise ValueError(f"Failed to read CSV file: {path}") from exc

    if df.empty:
        raise ValueError(f"Dataset is empty: {path}")

    return df