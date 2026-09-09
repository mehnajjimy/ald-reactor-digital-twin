from dataclasses import replace

import pytest

from ald_twin.configuration import Parameter, ParameterRegistry


def parameter(**kw):
    return Parameter(**(dict(name="diffusivity", symbol="D", value=.1, units="m^2 s^-1",
        source="deliberately selected synthetic coefficient", source_type="synthetic_verification",
        status="LOCKED", uncertainty=None, notes="No experimental interpretation") | kw))


def test_unresolved_dependent_run_is_blocked():
    p = parameter(value=None, source_type="unresolved", status="UNRESOLVED")
    registry = ParameterRegistry("missing-input", "experimental", (p,))
    with pytest.raises(ValueError, match="Blocked"):
        registry.resolve({"diffusivity": "m^2 s^-1"})


def test_synthetic_experimental_separation():
    with pytest.raises(ValueError, match="Synthetic"):
        ParameterRegistry("physical", "experimental", (parameter(),))


def test_registry_rejects_missing_units_and_duplicate_names():
    registry = ParameterRegistry("synthetic", "synthetic", (parameter(),))
    assert registry.resolve({"diffusivity": "m^2 s^-1"}) == {"diffusivity": .1}
    with pytest.raises(ValueError, match="expected"):
        registry.resolve({"diffusivity": "cm^2 s^-1"})
    with pytest.raises(ValueError, match="Missing"):
        registry.resolve({"velocity": "m s^-1"})
    with pytest.raises(ValueError, match="Duplicate"):
        ParameterRegistry("duplicate", "synthetic", (parameter(), parameter()))
    assert registry.sha256 != replace(registry, parameters=(parameter(value=.2),)).sha256


def test_derived_and_replacement_inputs_need_lineage():
    with pytest.raises(ValueError, match="parent"):
        parameter(source_type="derived")
    with pytest.raises(ValueError, match="incomplete"):
        parameter(details={"author_exact": False})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_nonphysical_scalar_encodings(value):
    with pytest.raises(ValueError):
        parameter(value=value)


def test_derived_value_cannot_hide_an_unresolved_parent():
    parent = parameter(value=None, status="UNRESOLVED", source_type="unresolved")
    derived = parameter(name="derived_D", source_type="derived",
        details={"parent_parameters": ["diffusivity"]})
    registry = ParameterRegistry("dependent", "experimental", (parent, derived))
    with pytest.raises(ValueError, match="Blocked"):
        registry.resolve({"derived_D": "m^2 s^-1"})


def test_cyclic_provenance_is_rejected_before_a_run():
    cyclic = parameter(source_type="derived", details={"parent_parameters": ["diffusivity"]})
    registry = ParameterRegistry("cyclic", "synthetic", (cyclic,))
    with pytest.raises(ValueError, match="Cyclic"):
        registry.resolve({"diffusivity": "m^2 s^-1"})
