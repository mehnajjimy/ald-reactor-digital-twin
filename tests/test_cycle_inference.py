"""parameter sensitivity, fitting and profiles against closed-form answers."""

import numpy as np
import pytest

from ald_twin.cycle_inference import fit_parameters, log_sensitivity, parameter_profile, sensitivity_report

# four observations that are linear in the log of three parameters
MATRIX = np.array([[1., 2., 1.], [.2, 3., 2.], [2., 1., 4.], [1., 1., 1.]])


def log_linear(values):
    """a model that is linear in log parameters, so its derivative is MATRIX."""
    return MATRIX @ np.log(values)


def one_observation(values):
    """a single observation that only sees the sum of the log parameters."""
    return np.array([np.log(values).sum()])


def test_log_sensitivity_and_fit_recover_a_known_model():
    """catches a wrong finite difference, a fit that stops early or a wrong profile cost."""
    truth = np.array([.02, 30., 50.])
    np.testing.assert_allclose(log_sensitivity(log_linear, truth), MATRIX, atol=1e-10)
    start = truth*np.array([.7, 1.3, .8])
    fitted, report = fit_parameters(log_linear, log_linear(truth), start, truth*.1, truth*10.)
    np.testing.assert_allclose(fitted, truth, rtol=1e-7)
    assert report["success"]

    # with y = log(p) the profile cost of scaling p0 by f is 0.5 log(f)²
    reference = np.ones(3)
    profile = parameter_profile(np.log, np.log(reference), reference, 0, [.5, 1., 2.],
                                reference*.1, reference*10.)
    assert all(point["converged"] for point in profile)
    np.testing.assert_allclose([point["cost"] for point in profile],
                               [.5*np.log(point["factor"])**2 for point in profile], atol=1e-14)


def test_one_observation_leaves_two_blind_directions_and_refuses_a_fit():
    """catches a rank-deficient problem being reported as uniquely fitted."""
    parameters = np.ones(3)
    derivative = log_sensitivity(one_observation, parameters)
    report = sensitivity_report(derivative, derivative)
    assert report["numerical_rank"] == 1
    assert report["singular_values"][1:] == [0., 0.]
    for direction in report["log_parameter_directions"][1:]:
        np.testing.assert_allclose(derivative @ direction, 0., atol=1e-12)
    with pytest.raises(ValueError, match="full-rank"):
        fit_parameters(one_observation, one_observation(parameters), parameters,
                       parameters*.1, parameters*10.)

    # moving along a blind direction costs nothing
    profile = parameter_profile(one_observation, one_observation(parameters), parameters, 0,
                                [.5, 1., 2.], parameters*.1, parameters*10.)
    np.testing.assert_allclose([point["cost"] for point in profile], 0., atol=1e-14)
