def dataset_overview(df):
    """
    Provide a high-level overview of the dataset structure.
    """
    return {
        "rows": len(df),
        "columns": df.columns.tolist(),
        "dtypes": df.dtypes.astype(str).to_dict(),
    }


def missing_summary(df):
    """
    Summarise missing values per column.
    """
    missing = df.isna().sum()
    missing_ratio = missing / len(df)

    return (
        missing
        .to_frame(name="missing_count")
        .assign(missing_ratio=missing_ratio)
    )


def numeric_summary(df):
    """
    Compute basic statistics for numeric columns.
    """
    return df.describe().T # Transpose for easier readability