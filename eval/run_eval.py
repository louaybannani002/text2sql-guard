"""Evaluate the text-to-SQL pipeline on eval/datasets and write eval/reports/.

Run from backend/ so the project's environment is used:

    cd backend
    uv run python ../eval/run_eval.py                  # all datasets, main model
    uv run python ../eval/run_eval.py --smoke          # 20-question CI subset (exit 1 below thresholds)
    uv run python ../eval/run_eval.py --model both     # compare main vs local (Ollama)
    uv run python ../eval/run_eval.py --help

The logic lives in backend/src/text2sql/eval/ (typed and tested); this file is the entry point.
"""

import sys

from text2sql.eval.cli import main

if __name__ == "__main__":
    sys.exit(main())
