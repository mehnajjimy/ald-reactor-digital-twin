import numpy as np
import pytest

from ald_twin.numerics import SolverOptions
from ald_twin.reactor_0d import FlowSegment, WellMixedReactor, solve_0d
from ald_twin.surface import FiniteCapacity
from ald_twin.verification import (ManufacturedSolution, advection_pulse_average,
    dimensional_checks, front_position, normalized_l1, restrict_uniform)


def test_exact_dimensions():
    assert all(dimensional_checks().values()), dimensional_checks()


def test_conservative_projection_and_discontinuous_reference():
    fine = np.array([[1., 3., 5., 7.]])
    np.testing.assert_array_equal(restrict_uniform(fine, 2), [[2., 6.]])
    assert fine.sum()*.25 == restrict_uniform(fine, 2).sum()*.5
    np.testing.assert_allclose(advection_pulse_average([0., .3, .6, .9, 1.2], 1., .75, 1.),
                               [1/6, 1, 1, 1/3])
    with pytest.raises(ValueError):
        restrict_uniform(fine, 3)
    with pytest.raises(ValueError, match="zero"):
        normalized_l1([1, 0], [0, 0])


def test_missing_or_ambiguous_front_is_not_a_zero_error():
    assert front_position([0., .5, 1.], [.9, .6, .2]) == pytest.approx(.625)
    for theta in ([1., .9, .8], [.9, .5, .5], [.9, .2, .8]):
        with pytest.raises(ValueError):
            front_position([0., .5, 1.], theta)


def test_manufactured_forcing_matches_independent_pointwise_quadrature():
    from numpy.polynomial.legendre import leggauss
    reference = ManufacturedSolution()
    z, dz, t = np.array([.125, .375, .625, .875]), .25, .3
    nodes, weights = leggauss(20)
    zz = z[:,None]+dz/2*nodes
    E, w = np.exp(-.7*t), np.pi
    c = E*np.sin(w*zz)
    theta = .2+.2*(1-E)*np.sin(w*zz)
    r = .5*c*(1-theta)
    sg = -.7*c+.4*E*w*np.cos(w*zz)+.1*w*w*c+r
    st = .2*.7*E*np.sin(w*zz)-r
    actual = reference.source_averages(t,z,dz,velocity=.4,diffusivity=.1,
        area_ratio=1.,capture_velocity=.5,capacity=1.)
    np.testing.assert_allclose(actual[0], sg@weights/2, atol=1e-14)
    np.testing.assert_allclose(actual[1], st@weights/2, atol=1e-14)


def test_output_sampling_preserves_switch_and_terminal_state():
    args = (WellMixedReactor(1.,1.,1.), FiniteCapacity(1.,2.),
            [FlowSegment(.4,1.),FlowSegment(.6,0.)])
    full = solve_0d(*args,concentration_scale=1.,options=SolverOptions(max_step=.05))
    sampled = solve_0d(*args,concentration_scale=1.,options=SolverOptions(max_step=.05),
                      output_times=[.1,.9])
    np.testing.assert_array_equal(sampled.t, [0., .1, .4, .9, 1.])
    np.testing.assert_array_equal(sampled.c[-1],full.c[-1])
    np.testing.assert_array_equal(sampled.theta[-1],full.theta[-1])
    assert sampled.solver_status[0]["end_state"] == sampled.solver_status[1]["start_state"]
    for invalid in ([.2,.1],[-1.],[2.],[np.nan]):
        with pytest.raises(ValueError,match="output_times"):
            solve_0d(*args,concentration_scale=1.,output_times=invalid)


def test_acceptance_runner_rejects_a_mislabeled_physical_unit(tmp_path,monkeypatch):
    import importlib.util
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location("acceptance_runner",root/"scripts/verify_phase1.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    document=json.loads((root/"config/synthetic/phase1-transport-pulse.json").read_text())
    for parameter in document["parameters"]:
        if parameter["name"]=="diffusivity":
            parameter["units"]="cm^2 s^-1"
    target=tmp_path/"config/synthetic"
    target.mkdir(parents=True)
    (target/"phase1-transport-pulse.json").write_text(json.dumps(document))
    monkeypatch.setattr(module,"ROOT",tmp_path)
    with pytest.raises(ValueError,match="expected m\\^2 s\\^-1"):
        module.Study("test").case("transport-pulse")
