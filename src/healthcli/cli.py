import argparse

# NOTE:
# This module defines the command line interface (CLI) structure only.
# The actual analysis logic is implemented in separate modules
# (e.g. quality.py, analysis.py).

def build_parser():
    """ This parser defines the overall purpose and available subcommands."""
    
    parser = argparse.ArgumentParser(
        prog="healthcli",
        description=(
            "Clinical Data Quality Analysis CLI.\n"
            "Assess data quality and perform basic analysis on "
            "clinical tabular datasets."
        )
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # quality command
    quality_parser = subparsers.add_parser(
        "quality",
        help="Assess data quality for clinical datasets"
    )

    quality_parser.add_argument(
        "--data",
        required=True,
        help="Path to the clinical CSV dataset"
    )

    quality_parser.add_argument(
        "--config",
        help="Path to the analysis configuration file (YAML)"
    )

    return parser