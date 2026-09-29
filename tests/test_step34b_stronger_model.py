"""Check that the paid comparison preserves its frozen source and model scope."""

from argparse import Namespace

import pytest

from scripts.evaluate_step34b_fixture_geometry import SYSTEM as REFERENCE_SYSTEM
from scripts.evaluate_step34b_stronger_model import (
    DEFAULT_MODEL_ID, REFERENCE_MODEL_ID, SYSTEM, evaluate,
)


def test_model_trial_reuses_exact_reference_system_prompt():
    assert SYSTEM == REFERENCE_SYSTEM
    assert DEFAULT_MODEL_ID == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert REFERENCE_MODEL_ID == "us.amazon.nova-2-lite-v1:0"


def test_wrong_model_blocks_evaluation_before_any_request():
    with pytest.raises(ValueError, match="documented Sonnet 4.5"):
        evaluate(Namespace(model_id=REFERENCE_MODEL_ID))
