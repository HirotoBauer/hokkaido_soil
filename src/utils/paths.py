# src/config/paths.py
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

# Top-level directories
DATA_DIR = ROOT_DIR / "data"
OUTPUTS_DIR = ROOT_DIR / "outputs"
CONFIG_DIR = ROOT_DIR / "config"
NOTEBOOKS_DIR = ROOT_DIR / "notebooks"

# Data subdirectories
RAW_DATA_DIR = DATA_DIR / "raw"
INTERM_DATA_DIR = DATA_DIR / "interm"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Output subdirectories
FIGURES_DIR = OUTPUTS_DIR / "figures"
TABLES_DIR = OUTPUTS_DIR / "tables"
