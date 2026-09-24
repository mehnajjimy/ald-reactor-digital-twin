"""parameter registry: units, provenance and blocked runs."""

import pytest

from ald_twin.configuration import Parameter, ParameterRegistry


def parameter(**changes):
    """a locked synthetic diffusivity, with any field changed."""
    fields = dict(name="diffusivity", symbol="D", value=.1, units="m^2 s^-1",
                  source="deliberately selected synthetic coefficient",
                  source_type="synthetic_verification", status="LOCKED",
                  uncertainty=None, notes="No experimental interpretation")
    fields.update(changes)
    return Parameter(**fields)


def test_registry_blocks_unresolved_mislabelled_or_cyclic_inputs():
    """catches a run that quietly uses a missing, wrong-unit or synthetic value."""
    registry = ParameterRegistry("synthetic", "synthetic", (parameter(),))
    assert registry.resolve({"diffusivity": "m^2 s^-1"}) == {"diffusivity": .1}
    with pytest.raises(ValueError, match="expected"):
        registry.resolve({"diffusivity": "cm^2 s^-1"})

    # synthetic numbers may not enter an experimental registry
    with pytest.raises(ValueError, match="Synthetic"):
        ParameterRegistry("physical", "experimental", (parameter(),))

    # an unresolved value blocks its own run and any value derived from it
    missing = parameter(value=None, source_type="unresolved", status="UNRESOLVED")
    derived = parameter(name="derived_D", source_type="derived",
                        details={"parent_parameters": ["diffusivity"]})
    registry = ParameterRegistry("dependent", "experimental", (missing, derived))
    for name in ("diffusivity", "derived_D"):
        with pytest.raises(ValueError, match="Blocked"):
            registry.resolve({name: "m^2 s^-1"})

    # a value derived from itself is rejected before any run
    cyclic = parameter(source_type="derived", details={"parent_parameters": ["diffusivity"]})
    with pytest.raises(ValueError, match="Cyclic"):
        ParameterRegistry("cyclic", "synthetic", (cyclic,)).resolve({"diffusivity": "m^2 s^-1"})
