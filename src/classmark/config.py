"""Constants that a reviewer should be able to find in one place.

Prices, model identifiers, caps and default thresholds live here so that a change
to any of them is a one-line, reviewable diff.
"""

from pathlib import Path

# Project layout. Paths are relative to the working directory so the tool can be
# run from the repository root.
ROOT = Path.cwd()
QUESTIONS_DIR = ROOT / "questions"
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
LOG_DIR = ROOT / "logs"
RESULTS_DIR = ROOT / "results"
REPORTS_DIR = ROOT / "reports"

# Models. Pin versioned IDs, not aliases, so results stay comparable over time.
# The response's own model field is logged as well.
JEV_MODEL = "jev-1.13.0"
CLAUDE_MODEL = "claude-haiku-5-5"
# Haiku 5.5 always runs adaptive thinking; effort controls how much it does.
# "low" suits single-shot classification. Thinking tokens are billed as output.
CLAUDE_EFFORT = "low"
CLAUDE_MAX_TOKENS = 4096

# Prices in US dollars per million tokens (checked 2026-10-10).
# Jev: https://docs.typesafe.ai/models (input only; output tokens are free).
# Claude Haiku 5.5: Anthropic API pricing, prompts up to 100k tokens.
PRICES = {
    "jev": {"input": 0.042, "output": 0.0},
    "claude": {"input": 0.10, "output": 0.50},
}

# Hard budget per run per backend, in US dollars. Override with --budget.
DEFAULT_BUDGET_USD = 2.0

# Profiler caps. The state is capped so that it stays small and relevant;
# Jev's accuracy falls as state fills with irrelevant detail.
STATE_CAP_CHARS = 6000
DESCRIPTION_CAP_CHARS = 1500
README_CAP_CHARS = 1500
LICENCE_CAP_CHARS = 600
MAX_LISTED_FILES = 30
MAX_TABLES = 3
MAX_TABLE_COLUMNS = 40
SAMPLE_ROWS = 3
CELL_CAP_CHARS = 40
MAX_ATTRIBUTES = 20
TEXT_FETCH_BYTES = 8 * 1024
TABLE_FETCH_BYTES = 16 * 1024
# netCDF/HDF5 headers can only be read from a whole file; skip larger files.
SCIENTIFIC_FILE_MAX_BYTES = 20 * 1024 * 1024

# Evaluation.
ECE_BINS = 15
TARGET_ACCURACY = 0.95
BEAM_WIDTH = 3
CONFIDENT_ERRORS_SHOWN = 10

# Polite HTTP client settings for public APIs.
USER_AGENT = "classmark/0.1 (research prototype; https://doi.org/10.15497/RDA00157)"
HTTP_TIMEOUT = 60.0
