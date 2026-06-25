"""
Automated quality report generation with HTML and PDF output.

Generates professional clinical data quality reports with:
- Missing data analysis with visualizations
- Clinical validation rule violations summary
- Data completeness metrics
"""

import base64
import io
import logging
from datetime import datetime
from typing import Dict, Optional

import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Template

try:
    from weasyprint import HTML
    WEASYPRINT_IMPORT_ERROR = None
except Exception as exc:
    HTML = None
    WEASYPRINT_IMPORT_ERROR = exc


class QualityReportGenerator:
    """
    Generates HTML and PDF quality reports.
    
    Usage:
        generator = QualityReportGenerator(logger)
        generator.generate_html_report(df, missing_summary, clinical_violations, output_path)
        generator.generate_pdf_report(html_path, pdf_path)
    """
    
    # Jinja2 HTML template with embedded CSS and placeholders
    TEMPLATE = Template("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Clinical Data Quality Report</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }
        h2 {
            color: #34495e;
            margin-top: 30px;
            border-left: 4px solid #3498db;
            padding-left: 10px;
        }
        .metadata {
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
            font-size: 0.95em;
        }
        .metric {
            display: inline-block;
            margin-right: 30px;
            margin-bottom: 10px;
        }
        .metric-label {
            font-weight: bold;
            color: #7f8c8d;
        }
        .metric-value {
            font-size: 1.3em;
            color: #2c3e50;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        th {
            background-color: #3498db;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }
        td {
            padding: 10px;
            border-bottom: 1px solid #ecf0f1;
        }
        tr:nth-child(even) {
            background-color: #f8f9fa;
        }
        .warning {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 10px;
            margin-bottom: 15px;
        }
        .error {
            background-color: #f8d7da;
            border-left: 4px solid #dc3545;
            padding: 10px;
            margin-bottom: 15px;
        }
        .chart-container {
            text-align: center;
            margin: 30px 0;
        }
        .chart-container img {
            max-width: 100%;
            height: auto;
            border: 1px solid #ecf0f1;
            border-radius: 4px;
        }
        .no-violations {
            background-color: #d4edda;
            color: #155724;
            padding: 10px;
            border-left: 4px solid #28a745;
            margin-bottom: 15px;
        }
        .footer {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
            font-size: 0.9em;
            color: #7f8c8d;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Clinical Data Quality Report</h1>
        
        <div class="metadata">
            <div class="metric">
                <div class="metric-label">Report Date:</div>
                <div class="metric-value">{{ report_date }}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Records:</div>
                <div class="metric-value">{{ total_records }}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Columns:</div>
                <div class="metric-value">{{ total_columns }}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Completeness:</div>
                <div class="metric-value">{{ completeness_pct }}%</div>
            </div>
        </div>
        
        <h2>Missing Data Analysis</h2>
        {% if missing_summary %}
            <table>
                <thead>
                    <tr>
                        <th>Column</th>
                        <th>Missing Count</th>
                        <th>Missing %</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                {% for col, missing_count, missing_pct in missing_summary %}
                    <tr>
                        <td>{{ col }}</td>
                        <td>{{ missing_count }}</td>
                        <td>{{ missing_pct | round(2) }}%</td>
                        <td>
                            {% if missing_pct > 30 %}
                                <span style="color: #dc3545; font-weight: bold;">⚠ HIGH</span>
                            {% elif missing_pct > 10 %}
                                <span style="color: #ffc107; font-weight: bold;">⚠ MODERATE</span>
                            {% else %}
                                <span style="color: #28a745; font-weight: bold;">✓ LOW</span>
                            {% endif %}
                        </td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        {% else %}
            <div class="no-violations">No missing data detected.</div>
        {% endif %}
        
        {% if chart_base64 %}
        <div class="chart-container">
            <h3>Missing Data by Column (Top 10)</h3>
            <img src="data:image/png;base64,{{ chart_base64 }}" alt="Missing data chart">
        </div>
        {% endif %}
        
        <h2>Clinical Validation Results</h2>
        {% if clinical_violations %}
            {% for rule_name, rule_details in clinical_violations.items() %}
            <div>
                <h3>{{ rule_name }}</h3>
                {% if rule_details['count'] > 0 %}
                    <div class="warning">
                        <strong>⚠ {{ rule_details['count'] }} violation(s) detected</strong>
                        <p>Severity: <strong>{{ rule_details['severity'] }}</strong></p>
                        <p>Affected rows: {{ rule_details['violations'] | join(', ') }}</p>
                    </div>
                {% else %}
                    <div class="no-violations">✓ No violations detected</div>
                {% endif %}
            </div>
            {% endfor %}
        {% else %}
            <div class="no-violations">✓ No clinical violations detected</div>
        {% endif %}

        <h2>FHIR-Inspired Model Validation</h2>
        {% if fhir_summary %}
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Patient rows validated</td>
                        <td>{{ fhir_summary.patients_validated }}</td>
                    </tr>
                    <tr>
                        <td>Patient validation errors</td>
                        <td>{{ fhir_summary.patient_errors }}</td>
                    </tr>
                    <tr>
                        <td>Observation rows validated</td>
                        <td>{{ fhir_summary.observations_validated }}</td>
                    </tr>
                    <tr>
                        <td>Observation validation errors</td>
                        <td>{{ fhir_summary.observation_errors }}</td>
                    </tr>
                </tbody>
            </table>
            {% if fhir_summary.errors %}
                <div class="warning">
                    <strong>FHIR model validation found errors.</strong>
                    <p>Example: {{ fhir_summary.errors[0] }}</p>
                </div>
            {% else %}
                <div class="no-violations">✓ No FHIR model validation errors detected</div>
            {% endif %}
        {% else %}
            <div class="no-violations">FHIR model validation was not executed.</div>
        {% endif %}
        
        <div class="footer">
            <p>This report was automatically generated by Clinical Data Quality Analysis Tool.</p>
            <p>For questions or data corrections, please contact your data quality team.</p>
        </div>
    </div>
</body>
</html>
    """)
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("healthcli.quality_report")
    
    def _generate_missing_chart_base64(self, df: pd.DataFrame) -> str:
        """
        Generate missing data bar chart and encode as base64 PNG.
        
        Shows top 10 columns by missing count, embedded in HTML as data URI.
        """
        # Calculate missing data by column
        missing_counts = df.isnull().sum().sort_values(ascending=False)
        top_10 = missing_counts.head(10)
        
        if len(top_10) == 0 or top_10.sum() == 0:
            return ""
        
        # Create bar chart
        fig, ax = plt.subplots(figsize=(10, 5))
        top_10.plot(kind="bar", ax=ax, color="#3498db")
        ax.set_title("Missing Data by Column (Top 10)", fontsize=14, fontweight="bold")
        ax.set_xlabel("Column", fontsize=12)
        ax.set_ylabel("Missing Count", fontsize=12)
        ax.grid(axis="y", alpha=0.3)
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        
        # Encode to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format="png", dpi=100)
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.read()).decode()
        plt.close(fig)
        
        return image_base64
    
    def generate_html_report(
        self,
        df: pd.DataFrame,
        missing_summary: Optional[Dict] = None,
        clinical_violations: Optional[Dict] = None,
        fhir_summary: Optional[Dict] = None,
        output_path: str = "quality_report.html",
    ) -> None:
        """
        Generate HTML quality report.
        
        Args:
            df: Input DataFrame
            missing_summary: Dict with column -> {count, pct} missing data
            clinical_violations: Dict with rule_name -> {count, severity, violations}
            output_path: Output HTML file path
        """
        # Prepare metadata
        total_records = len(df)
        total_columns = len(df.columns)
        total_cells = total_records * total_columns
        missing_cells = df.isnull().sum().sum()
        completeness_pct = round((1 - missing_cells / total_cells) * 100, 2)
        
        # Prepare missing summary table data
        missing_table = []
        if missing_summary:
            for col, info in missing_summary.items():
                missing_count = info.get("count", 0)
                missing_pct = info.get("pct", 0)
                missing_table.append((col, missing_count, missing_pct))
        
        # Prepare clinical violations summary
        violations_summary = {}
        if clinical_violations:
            for rule_name, result in clinical_violations.items():
                violations_summary[rule_name] = {
                    "count": result.count,
                    "severity": result.severity,
                    "violations": result.violations[:20],  # Limit to first 20
                }
        
        # Generate chart
        chart_base64 = self._generate_missing_chart_base64(df)

        # Render template
        html_content = self.TEMPLATE.render(
            report_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_records=total_records,
            total_columns=total_columns,
            completeness_pct=completeness_pct,
            missing_summary=missing_table,
            clinical_violations=violations_summary,
            fhir_summary=fhir_summary,
            chart_base64=chart_base64,
        )

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        self.logger.info(f"HTML report generated: {output_path}")

    def generate_pdf_report(self, html_path: str, pdf_path: str) -> None:
        """
        Convert HTML report to PDF using WeasyPrint.

        Args:
            html_path: Path to HTML file
            pdf_path: Output PDF file path

        Raises:
            RuntimeError: If WeasyPrint is not installed
        """
        if HTML is None:
            if WEASYPRINT_IMPORT_ERROR is not None:
                self.logger.error(
                    "WeasyPrint import failed: %s",
                    WEASYPRINT_IMPORT_ERROR,
                )
                self.logger.error(
                    "WeasyPrint requires additional system dependencies."
                    " See https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation"
                )
            else:
                self.logger.error(
                    "WeasyPrint not installed. Install with: pip install weasyprint"
                )
            raise RuntimeError("WeasyPrint is required for PDF generation")

        try:
            HTML(html_path).write_pdf(pdf_path)
            self.logger.info(f"PDF report generated: {pdf_path}")
        except Exception as e:
            self.logger.error(f"Failed to generate PDF: {e}")
            raise
