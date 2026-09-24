"""verification helpers: manufactured sources against independent quadrature."""


import numpy as np
from numpy.polynomial.legendre import leggauss

from ald_twin.verification import ManufacturedSolution


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
