"""Bound repeated work in the real encoded audio callback; no device access."""
import pytest

import profile_glasshouse


@pytest.fixture(scope='module')
def measured():
    return profile_glasshouse.profile(blocks=2)


@pytest.mark.parametrize('width,configuration,limit', [
    (1, 'default', 18000), (2, 'default', 28000),
    (1, 'complex', 28000), (2, 'complex', 45000),
])
def test_encoded_callback_stays_within_instruction_budget(measured, width, configuration, limit):
    case = next(case for case in measured['cases']
                if case['width'] == width and case['configuration'] == configuration)
    assert case['steady_max'] <= limit, case
    assert measured['counts_are_hardware_cycles'] is False
