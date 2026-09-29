import json
import os

from src.core.admin_ops.application.evaluation.run_eval import DEFAULT_DATASET_PATH


def test_default_dataset_path_resolves_independent_of_cwd(tmp_path):
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        entries = json.loads(DEFAULT_DATASET_PATH.read_text())
    finally:
        os.chdir(cwd)

    assert DEFAULT_DATASET_PATH.is_absolute()
    assert entries and all({"query", "ideal_context", "ideal_answer"} <= set(e) for e in entries)
