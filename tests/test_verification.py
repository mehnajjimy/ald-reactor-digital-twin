"""verification helpers: projections, manufactured sources and output sampling."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from numpy.polynomial.legendre import leggauss

from ald_twin.numerics import SolverOptions
from ald_twin.reactor_0d import FlowSegment, WellMixedReactor, solve_0d
from ald_twin.surface import FiniteCapacity
from ald_twin.verification import ManufacturedSolution, advection_pulse_average, restrict_uniform


def test_projection_and_pulse_average_match_hand_values():
    """catches a coarse-grid average that loses mass or a wrong pulse cell average."""
    fine = np.array([[1., 3., 5., 7.]])
    np.testing.assert_array_equal(restrict_uniform(fine, 2), [[2., 6.]])
    assert fine.sum()*.25 == restrict_uniform(fine, 2).sum()*.5
    # a unit pulse on [0.25, 1] covers 1/6 of the first cell and 1/3 of the last
    np.testing.assert_allclose(advection_pulse_average([0., .3, .6, .9, 1.2], 1., .75, 1.),
                               [1/6, 1, 1, 1/3])


def test_manufactured_forcing_matches_independent_quadrature():
    """catches a wrong term in the manufactured gas or surface source."""
    # c = exp(-0.7 t) sin(pi z), theta = 0.2 + 0.2 (1 - exp(-0.7 t)) sin(pi z),
    # u = 0.4, D = 0.1, k = 0.5, averaged over each cell by 20-point gauss quadrature
    z, dz, t = np.array([.125, .375, .625, .875]), .25, .3
    nodes, weights = leggauss(20)
    zz = z[:, None]+dz/2*nodes
    decay, wave = np.exp(-.7*t), np.pi
    c = decay*np.sin(wave*zz)
    theta = .2+.2*(1-decay)*np.sin(wave*zz)
    rate = .5*c*(1-theta)
    gas_source = -.7*c+.4*decay*wave*np.cos(wave*zz)+.1*wave*wave*c+rate
    surface_source = .2*.7*decay*np.sin(wave*zz)-rate
    actual = ManufacturedSolution().source_averages(t, z, dz, velocity=.4, diffusivity=.1,
        area_ratio=1., capture_velocity=.5, capacity=1.)
    np.testing.assert_allclose(actual[0], gas_source@weights/2, atol=1e-14)
    np.testing.assert_allclose(actual[1], surface_source@weights/2, atol=1e-14)


def test_output_sampling_keeps_the_switch_and_final_state():
    """catches requested output times changing the answer or dropping the segment switch."""
    args = (WellMixedReactor(1., 1., 1.), FiniteCapacity(1., 2.),
            [FlowSegment(.4, 1.), FlowSegment(.6, 0.)])
    full = solve_0d(*args, concentration_scale=1., options=SolverOptions(max_step=.05))
    sampled = solve_0d(*args, concentration_scale=1., options=SolverOptions(max_step=.05),
                       output_times=[.1, .9])
    np.testing.assert_array_equal(sampled.t, [0., .1, .4, .9, 1.])
    np.testing.assert_array_equal(sampled.c[-1], full.c[-1])
    np.testing.assert_array_equal(sampled.theta[-1], full.theta[-1])
    assert sampled.solver_status[0]["end_state"] == sampled.solver_status[1]["start_state"]


def test_acceptance_runner_rejects_a_mislabelled_unit(tmp_path, monkeypatch):
    """catches the phase 1 runner accepting a diffusivity in the wrong unit."""
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("acceptance_runner", root/"scripts/verify_phase1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    document = json.loads((root/"config/synthetic/phase1-transport-pulse.json").read_text())
    for parameter in document["parameters"]:
        if parameter["name"] == "diffusivity":
            parameter["units"] = "cm^2 s^-1"
    target = tmp_path/"config/synthetic"
    target.mkdir(parents=True)
    (target/"phase1-transport-pulse.json").write_text(json.dumps(document))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="expected m\\^2 s\\^-1"):
        module.Study("test").case("transport-pulse")
