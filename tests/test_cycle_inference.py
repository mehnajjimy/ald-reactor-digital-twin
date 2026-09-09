"""Independent derivative and rank checks before the slower reactor recovery run."""

import numpy as np
import pytest

from ald_twin.cycle_inference import fit_parameters, log_sensitivity, parameter_profile, sensitivity_report


def test_log_derivative_matches_closed_form_and_recovers_parameters():
    matrix = np.array([[1., 2., 1.], [.2, 3., 2.], [2., 1., 4.], [1., 1., 1.]])
    predict = lambda values: matrix @ np.log(values)
    truth = np.array([.02, 30., 50.])
    derivative = log_sensitivity(predict, truth)
    np.testing.assert_allclose(derivative, matrix, atol=1e-10)
    initial = truth*np.array([.7, 1.3, .8])
    fitted, report = fit_parameters(predict, predict(truth), initial, truth*.1, truth*10.)
    np.testing.assert_allclose(fitted, truth, rtol=1e-7)
    assert report["success"]


def test_single_observation_preserves_two_null_directions_and_refuses_unique_fit():
    predict = lambda values: np.array([np.log(values).sum()])
    parameters = np.ones(3)
    derivative = log_sensitivity(predict, parameters)
    report = sensitivity_report(derivative, derivative)
    assert report["numerical_rank"] == 1
    assert report["singular_values"][1:] == [0., 0.]
    for direction in report["log_parameter_directions"][1:]:
        np.testing.assert_allclose(derivative @ direction, 0., atol=1e-12)
    with pytest.raises(ValueError, match="full-rank"):
        fit_parameters(predict, predict(parameters), parameters, parameters*.1, parameters*10.)


def test_profile_matches_independent_quadratic_and_flat_limits():
    reference = np.ones(3)
    for predict, exact_cost in ((np.log, lambda factor: .5*np.log(factor)**2),
                               (lambda values: np.array([np.log(values).sum()]), lambda factor: 0.)):
        profile = parameter_profile(predict, predict(reference), reference, 0, [.5, 1., 2.], reference*.1, reference*10.)
        assert all(point["converged"] for point in profile)
        np.testing.assert_allclose([point["cost"] for point in profile],
                                   [exact_cost(point["factor"]) for point in profile], atol=1e-14)
