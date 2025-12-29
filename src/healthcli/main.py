from data_loader import load_csv_data
from quality import (
    dataset_overview,
    missing_summary,
    numeric_summary,
)


def main():
    data_path = "data/diabetic_data.csv"
    df = load_csv_data(data_path)

    # Dataset overview
    overview = dataset_overview(df)

    print("=== Dataset Overview ===")
    print(overview)

    # Missing values
    missing = missing_summary(df)
    print("\n=== Missing Value Summary ===")
    print(missing.head())

    # Numeric summary
    numeric = numeric_summary(df)

    print("\n=== Numeric Summary ===")
    print(numeric.head())


if __name__ == "__main__":
    main()