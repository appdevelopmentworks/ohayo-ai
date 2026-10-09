"""Repository paths. Generated output goes only to DATA_DIR and PUBLIC_DIR."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PUBLIC_DIR = ROOT / "public"
TEMPLATES_DIR = ROOT / "templates"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
