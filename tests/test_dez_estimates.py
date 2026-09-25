"""the DEZ and water estimate process against hand-worked values."""

import numpy as np
import pytest

from ald_twin.cycle_transport import channel_grid
from ald_twin.cycles import periodic_cycle, periodic_gpc
from ald_twin.gas_properties import dez_nitrogen_diffusivity
from ald_twin.process_inputs import load_process, prepare_inputs


def test_dez_diffusivity_and_saturated_growth_match_hand_values():
    """catches a wrong DEZ transport estimate or a wrong ZnO film mapping."""
    # Chapman-Enskog by hand for DEZ-N2 at 423.15 K and 200 Pa: sigma 4.829 A,
    # epsilon/k 170.05 K, T* 2.488, Neufeld omega 1.0018, pair mass 45.67 g/mol
    assert dez_nitrogen_diffusivity(423.15, 200) == pytest.approx(7.333e-3, rel=2e-4)
    data = load_process("dez-water-zno")
    assert data["diffusivity"]["a"]["value"] == dez_nitrogen_diffusivity(423.15, 200)

    # a filled surface holds 6.6 Zn per nm2 = 1.0960e-5 mol/m2, and
    # 1.0960e-5 mol/m2 * 0.081379 kg/mol / 5300 kg/m3 = 1.6828 A per cycle
    data, chemistry, segments, _ = prepare_inputs(data)
    result = periodic_cycle(channel_grid(data, 40), chemistry, segments,
                            fraction_scale=data["fraction_scale"])
    gpc = periodic_gpc(result, data["film"]["density_kg_m3"])
    assert gpc == pytest.approx(1.6828 * result.turnover, rel=1e-4)

    # the half-second pulses nearly fill the surface along the whole channel
    assert np.min(result.turnover) > .98
