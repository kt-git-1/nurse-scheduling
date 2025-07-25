# nurse-scheduling

This project optimizes nurse shift schedules using [OR-Tools](https://developers.google.com/optimization/).

## Requirements

- Python 3.10+
- pandas
- openpyxl
- ortools

Install all dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

1. Prepare the request CSV (`req_shift_8.csv`) and the Excel template (`shift_template.xlsx`).
2. Run the main script:

```bash
python main.py
```

The optimized schedule will be written to `shift_output.xlsx`.

## Repository Structure

- `config.py` – configuration values and `load_config` helper.
- `optimize_1.py` – first optimization pass with strict constraints.
- `optimize_2.py` – second optimization with soft constraints.
- `optimize_shift.py` – sample script for writing results to Excel.
- `main.py` – coordinates the optimization steps.

