# FHIR / Clinical Data Pipeline

医療データ品質チェックを、Pandas/NumPy の単純な検証から FHIR 準拠の臨床データパイプラインへ進化させます。
このリポジトリは、EHR や臨床試験のデータに対して再現性のあるルールベース検証と Pydantic モデル検証を組み合わせた品質パイプラインを提供します。

## Problem addressed

電子カルテ（EHR）や臨床試験データは、表記ゆれ、欠損、非現実的なバイタル値（例: 血圧 300 mmHg）、
コーディング不整合、時系列の急変を含みます。そのまま分析や機械学習に使うと、
医療的に意味のない結果や誤った意思決定を生みます。

このプロジェクトは、医療ドメイン固有のバリデーションルールを適用し、
再現性のあるクレンジングとレポート生成を行うデータパイプラインを目指します。

## What it does

- FHIR-inspired Pydantic モデルで患者 / 観察結果 / バイタルサインを構造化検証
- 年齢と検査値の不整合、時系列バイタル急変、不自然な欠損パターンを決定論的ルールで検出
- 欠損率、臨床違反、FHIR 検証結果を HTML / PDF レポートで自動出力
- EHR/Clinical Trials 向けのデータ品質パイプラインとして再現可能に実行

## Key features

- `Patient`, `Observation`, `VitalSigns` の Pydantic FHIR-inspired モデル
- `ClinicalCoherenceRule`, `VitalSignAnomalyRule`, `MissingDataThresholdRule` の臨床ルールエンジン
- FHIR モデル検証のサマリを含む自動レポート生成
- パイプライン実行時に `quality_report.html` と `quality_report.pdf` を生成

## Usage

Run data quality analysis:

```bash
healthcli quality --data data/diabetic_data.csv --config config/config.yaml
```

Run the pipeline and write outputs:

```bash
healthcli pipeline --data data/diabetic_data.csv --config config/config.yaml --output output
```

The pipeline writes:

- `output/missing_summary.csv`
- `output/quality_report.html`
- `output/quality_report.pdf` (if WeasyPrint and its system dependencies are available)

It also logs progress to `logs/`.

> PDF output is now supported when WeasyPrint and its system dependencies are available.

## Architecture

- `src/healthcli/data_loader.py`: CSV ロードと基本的な読み込み検証
- `src/healthcli/fhir_models.py`: FHIR-inspired Pydantic モデルによる型・範囲検証
- `src/healthcli/clinical_rules_extended.py`: 臨床ドメイン固有ルールエンジン
- `src/healthcli/quality.py`: 欠損サマリと FHIR モデル検証の集計
- `src/healthcli/quality_report.py`: HTML/PDF レポート生成

## Tech stack

- Python 3.9+
- Pandas, NumPy
- Pydantic v2
- Jinja2
- WeasyPrint
- Matplotlib
- PyYAML

## Why this matters

このパイプラインは、EHR や臨床試験データの信頼性を高めるための実務的な設計です。
容量のある医療データ品質管理、監査対応、分析前のクレンジングに向けた土台を提供します。
