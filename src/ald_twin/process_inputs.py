"""explicit inputs for synthetic, one-to-one, two-half-cycle examples."""

from copy import deepcopy
import json
from pathlib import Path

from .channel_flow import channel_flow
from .cycle_transport import channel_grid
from .cycles import CycleChemistry, CycleSegment
from .units import _nonnegative, _positive

PROCESS_DIRECTORY = Path(__file__).with_name("processes")
UNITS = {"channel.length": "m", "channel.width": "m", "channel.height": "m",
         "channel.temperature": "K", "channel.outlet_pressure": "Pa",
         "channel.molar_flow": "mol/s", "channel.viscosity": "Pa s",
         "reactive_interval": "m", "diffusivity": "m2/s at reference K and Pa",
         "chemistry.capacity": "mol/m2", "chemistry.rate_a": "m3/(mol s)",
         "chemistry.rate_b": "m3/(mol s)", "fraction_scale": "1",
         "recipe": "residence times"}
PROVENANCE_SECTIONS = ("channel", "diffusivity", "chemistry", "recipe", "film")


def process_catalog():
    return [json.loads(path.read_text()) for path in sorted(PROCESS_DIRECTORY.glob("*.json"))]


def load_process(name_or_path):
    path = Path(name_or_path)
    if not path.is_file():
        path = next((p for p in PROCESS_DIRECTORY.glob("*.json") if p.stem == str(name_or_path)), None)
    if path is None:
        raise ValueError(f"Unknown process: {name_or_path}; use 'ald-twin processes'")
    return json.loads(path.read_text())


def input_issues(data):
    """return missing/unsupported inputs for the cli and gui to display."""

    issues = []
    if not isinstance(data, dict):
        return ["The process input must be a JSON object"]
    try:

        # saved metadata must contain finite, serializable values.

        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        return [f"Inputs must contain finite JSON values: {error}"]
    fields = {"schema_version", "id", "name", "kind", "physical_fit_ready", "model", "species",
              "channel", "reactive_interval", "fraction_scale", "diffusivity", "chemistry",
              "recipe", "film", "spatial_grids", "units", "provenance"}
    if set(data) - fields:
        issues.append(f"Unknown input fields: {', '.join(sorted(str(key) for key in set(data) - fields))}")
    for section in ("channel", "diffusivity", "chemistry", "recipe"):
        if not isinstance(data.get(section), dict):
            issues.append(f"{section} must be an input object")
    if issues:
        return issues
    if set(data["diffusivity"]) != {"a", "b"} or any(
            not isinstance(prop, dict) for prop in data["diffusivity"].values()):
        return ["diffusivity requires an explicit property object for a and b"]
    if "reactive_interval" not in data:
        issues.append("reactive_interval is required; no reactive-area default is selected")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        issues.append("schema_version must be the integer 1")
    for name, prop in data["diffusivity"].items():
        allowed = {"kind", "source", "source_type", "value", "temperature", "pressure", "uncertainty"}
        if set(prop) - allowed:
            issues.append(f"Unknown diffusivity.{name} fields: {', '.join(sorted(str(key) for key in set(prop) - allowed))}")
        if not isinstance(prop.get("source"), str) or not prop["source"].strip():
            issues.append(f"diffusivity.{name}.source must be a nonempty description")
        if prop.get("source_type") != "synthetic_verification":
            issues.append(f"diffusivity.{name}.source_type must be synthetic_verification")
    for key in ("id", "name"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            issues.append(f"{key} is required")
    if data.get("kind") != "synthetic" or data.get("physical_fit_ready") is not False:
        issues.append("Physical runs remain blocked; kind must be synthetic and physical_fit_ready false")
    if data.get("model") != "two-event-nu1":
        issues.append("Only the existing two-event-nu1 equations are supported")
    species = data.get("species", {})
    if not isinstance(species, dict) or set(species) != {"a", "b"} or any(
            not isinstance(value, str) or not value.strip() for value in species.values()):
        issues.append("Two explicit species labels, a and b, are required")
    if data.get("units") != UNITS:
        issues.append("Units must match the declared SI input reference exactly")
    for section in PROVENANCE_SECTIONS:
        source = data.get("provenance", {}).get(section, {}) if isinstance(data.get("provenance"), dict) else {}
        if (not isinstance(source, dict)
                or not isinstance(source.get("source"), str) or not source["source"].strip()
                or source.get("source_type") != "synthetic_verification"
                or not isinstance(source.get("validity"), str) or not source["validity"].strip()):
            issues.append(f"provenance.{section} needs a synthetic source and explicit validity")
    try:
        channel = data["channel"]
        channel_flow([0, channel["length"]], **channel)
        if channel["temperature"] != 423.15:
            issues.append("This input path is limited to 423.15 K; no temperature kinetics are defined")
        scale = _positive(data["fraction_scale"], "fraction_scale")
        if scale > .01:
            issues.append("fraction_scale exceeds the declared synthetic trace scale 0.01")
        chemistry = data["chemistry"]
        CycleChemistry(**chemistry)

        # cycle diagnostics need both reaction events.

        _positive(chemistry["rate_a"], "chemistry.rate_a")
        _positive(chemistry["rate_b"], "chemistry.rate_b")
        interval = data["reactive_interval"]
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError("reactive_interval must contain two positions in metres")
        for position in interval:
            _nonnegative(position, "reactive_interval position")
        grid = channel_grid(data, 1)
        if grid.reactive_areas.sum() <= 0:
            issues.append("A positive reactive area is required")
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        issues.append(f"Required reactor/transport/chemistry input: {error}")
    try:
        recipe = data["recipe"]
        if set(recipe) != {"a_pulse", "a_purge", "b_pulse", "b_purge"}:
            raise ValueError("recipe requires a_pulse, a_purge, b_pulse, b_purge")
        for name, value in recipe.items():
            if _positive(value, f"recipe.{name}") > 20:
                raise ValueError("Each segment is bounded at 20 residence times")
        grids = data["spatial_grids"]
        if (not isinstance(grids, list) or len(grids) < 2
                or any(type(n) is not int or n < 2 or n > 2560 for n in grids)
                or any(b != 2*a for a, b in zip(grids, grids[1:]))):
            raise ValueError("spatial_grids must double, with at least two grids and ceiling 2560")
    except (KeyError, TypeError, ValueError) as error:
        issues.append(f"Required recipe/numerical input: {error}")
    if "film" not in data:
        issues.append("film is required; use null when no supported thickness mapping exists")
    elif data["film"] is not None and data["film"] != {
            "mapping": "conditional-zno-150c", "density_kg_m3": 5400.0}:
        issues.append("Only the fixed conditional ZnO mapping is supported; otherwise film must be null")
    if data.get("film") is not None and (data.get("id") != "synthetic-zno"
            or species != {"a": "DEZ-like synthetic A", "b": "Water-like synthetic B"}):
        issues.append("The ZnO mapping cannot be transferred to another process")
    return issues


def prepare_inputs(data):
    """validate before constructing flow, chemistry or a recipe for calculation."""

    data = deepcopy(data)
    issues = input_issues(data)
    if issues:
        raise ValueError("; ".join(issues))
    mixed = channel_grid(data, 1)
    residence = float(mixed.carrier_moles.sum() / mixed.molar_flow)
    feed = mixed.molar_flow * data["fraction_scale"]
    ratios = data["recipe"]
    segments = [CycleSegment(ratios["a_pulse"]*residence, feed, 0., "A pulse"),
                CycleSegment(ratios["a_purge"]*residence, 0., 0., "A purge"),
                CycleSegment(ratios["b_pulse"]*residence, 0., feed, "B pulse"),
                CycleSegment(ratios["b_purge"]*residence, 0., 0., "B purge")]
    return data, CycleChemistry(**data["chemistry"]), segments, residence


def inspect_process(data):
    """describe required inputs without invoking the integrator."""

    issues = input_issues(data)
    report = dict(inputs=data, issues=issues, runnable=not issues, physical_fit_ready=False)
    if issues:
        return report
    parameters, chemistry, segments, residence = prepare_inputs(data)
    channel = parameters["channel"]
    pressure, velocity = channel_flow([0, channel["length"]], **channel)
    report["flow"] = dict(residence_s=residence, pressure_pa=pressure.tolist(),
                          mean_velocity_m_s=velocity.tolist(),
                          segment_duration_s=[s.duration for s in segments],
                          precursor_moles=sum(s.duration*(s.inlet_a+s.inlet_b) for s in segments))
    report["film_status"] = "Conditional synthetic ZnO equivalent" if data["film"] else "Unavailable; surface turnover only"
    return report
