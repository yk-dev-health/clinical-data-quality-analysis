import argparse

"""
Command line interface (CLI) definition for the project.

This module defines available commands and arguments only.
It does not contain any data processing or analysis logic.

Actual analysis is implemented in separate modules
(e.g. quality.py, analysis.py).
"""

def build_parser():
    """
    Create and return the argument parser for the CLI.
    This function defines available commands and their arguments.
    """
    
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