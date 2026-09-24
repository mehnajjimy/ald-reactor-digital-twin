"""explicit inputs for synthetic, one-to-one, two-half-cycle examples."""

from copy import deepcopy
import json
from pathlib import Path

from .channel_flow import channel_flow
from .cycle_transport import channel_grid
from .cycles import CycleChemistry, CycleSegment
from .units import _nonnegative, _positive

# where the bundled process files live and the unit reference every input must repeat

PROCESS_DIRECTORY = Path(__file__).with_name("processes")
UNITS = {"channel.length": "m", "channel.width": "m", "channel.height": "m",
         "channel.temperature": "K", "channel.outlet_pressure": "Pa",
         "channel.molar_flow": "mol/s", "channel.viscosity": "Pa s",
         "reactive_interval": "m", "diffusivity": "m2/s at reference K and Pa",
         "chemistry.capacity": "mol/m2", "chemistry.rate_a": "m3/(mol s)",
         "chemistry.rate_b": "m3/(mol s)", "fraction_scale": "1",
         "recipe": "residence times"}
PROVENANCE_SECTIONS = ("channel", "diffusivity", "chemistry", "recipe", "film")

# allowed fields and fixed limits for the synthetic input path

INPUT_FIELDS = {"schema_version", "id", "name", "kind", "physical_fit_ready", "model", "species",
                "channel", "reactive_interval", "fraction_scale", "diffusivity", "chemistry",
                "recipe", "film", "spatial_grids", "units", "provenance"}
DIFFUSIVITY_FIELDS = {"kind", "source", "source_type", "value", "temperature", "pressure", "uncertainty"}
OBJECT_SECTIONS = ("channel", "diffusivity", "chemistry", "recipe")
RECIPE_KEYS = {"a_pulse", "a_purge", "b_pulse", "b_purge"}
SYNTHETIC_SOURCE = "synthetic_verification"
SUPPORTED_TEMPERATURE_K = 423.15
MAX_FRACTION_SCALE = .01
MAX_SEGMENT_RESIDENCE_TIMES = 20
MIN_GRID_CELLS = 2
MAX_GRID_CELLS = 2560
ZNO_FILM = {"mapping": "conditional-zno-150c", "density_kg_m3": 5400.0}
ZNO_SPECIES = {"a": "DEZ-like synthetic A", "b": "Water-like synthetic B"}


# loading process files

def process_catalog():
    """return every bundled process, sorted by file name."""

    catalog = []
    for path in sorted(PROCESS_DIRECTORY.glob("*.json")):
        catalog.append(json.loads(path.read_text()))
    return catalog


def load_process(name_or_path):
    """load a process from a file path or a bundled process name."""

    path = Path(name_or_path)
    if not path.is_file():
        path = None
        for candidate in PROCESS_DIRECTORY.glob("*.json"):
            if candidate.stem == str(name_or_path):
                path = candidate
                break
    if path is None:
        raise ValueError(f"Unknown process: {name_or_path}; use 'ald-twin processes'")
    return json.loads(path.read_text())


# small checks used by input_issues

def _is_text(value):
    """true for a string that is not blank."""

    return isinstance(value, str) and bool(value.strip())


def _unknown_keys(keys, allowed):
    """sorted, comma-separated names of keys that are not allowed."""

    return ', '.join(sorted(str(key) for key in set(keys) - allowed))


def _valid_species(species):
    """true when species has exactly the labels a and b, both nonblank text."""

    if not isinstance(species, dict) or set(species) != {"a", "b"}:
        return False
    for value in species.values():
        if not _is_text(value):
            return False
    return True


def _valid_provenance(source):
    """true when a provenance entry names a synthetic source and its validity."""

    return (isinstance(source, dict)
            and _is_text(source.get("source"))
            and source.get("source_type") == SYNTHETIC_SOURCE
            and _is_text(source.get("validity")))


def _valid_grids(grids):
    """true when grids is a list of at least two cell counts that double each time."""

    if not isinstance(grids, list) or len(grids) < 2:
        return False
    for cells in grids:
        if type(cells) is not int or cells < MIN_GRID_CELLS or cells > MAX_GRID_CELLS:
            return False
    for smaller, larger in zip(grids, grids[1:]):
        if larger != 2*smaller:
            return False
    return True


def _add_reactor_issues(data, issues):
    """add channel, scale and reactive-area issues, and raise when an input cannot be built.

    issues is filled in place so anything found before a raise is kept.
    """

    channel = data["channel"]
    channel_flow([0, channel["length"]], **channel)
    if channel["temperature"] != SUPPORTED_TEMPERATURE_K:
        issues.append("This input path is limited to 423.15 K; no temperature kinetics are defined")
    scale = _positive(data["fraction_scale"], "fraction_scale")
    if scale > MAX_FRACTION_SCALE:
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


def _check_recipe_and_grids(data):
    """raise when the recipe or spatial grids are missing or out of bounds."""

    recipe = data["recipe"]
    if set(recipe) != RECIPE_KEYS:
        raise ValueError("recipe requires a_pulse, a_purge, b_pulse, b_purge")
    for name, value in recipe.items():
        if _positive(value, f"recipe.{name}") > MAX_SEGMENT_RESIDENCE_TIMES:
            raise ValueError("Each segment is bounded at 20 residence times")
    if not _valid_grids(data["spatial_grids"]):
        raise ValueError("spatial_grids must double, with at least two grids and ceiling 2560")


# full input check

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

    # top-level shape: stop early on unknown fields or a section that is not an object

    if set(data) - INPUT_FIELDS:
        issues.append(f"Unknown input fields: {_unknown_keys(data, INPUT_FIELDS)}")
    for section in OBJECT_SECTIONS:
        if not isinstance(data.get(section), dict):
            issues.append(f"{section} must be an input object")
    if issues:
        return issues
    diffusivity = data["diffusivity"]
    if set(diffusivity) != {"a", "b"}:
        return ["diffusivity requires an explicit property object for a and b"]
    for prop in diffusivity.values():
        if not isinstance(prop, dict):
            return ["diffusivity requires an explicit property object for a and b"]

    # labels, gates and provenance

    if "reactive_interval" not in data:
        issues.append("reactive_interval is required; no reactive-area default is selected")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        issues.append("schema_version must be the integer 1")
    for name, prop in diffusivity.items():
        if set(prop) - DIFFUSIVITY_FIELDS:
            issues.append(f"Unknown diffusivity.{name} fields: {_unknown_keys(prop, DIFFUSIVITY_FIELDS)}")
        if not _is_text(prop.get("source")):
            issues.append(f"diffusivity.{name}.source must be a nonempty description")
        if prop.get("source_type") != SYNTHETIC_SOURCE:
            issues.append(f"diffusivity.{name}.source_type must be synthetic_verification")
    for key in ("id", "name"):
        if not _is_text(data.get(key)):
            issues.append(f"{key} is required")
    if data.get("kind") != "synthetic" or data.get("physical_fit_ready") is not False:
        issues.append("Physical runs remain blocked; kind must be synthetic and physical_fit_ready false")
    if data.get("model") != "two-event-nu1":
        issues.append("Only the existing two-event-nu1 equations are supported")
    species = data.get("species", {})
    if not _valid_species(species):
        issues.append("Two explicit species labels, a and b, are required")
    if data.get("units") != UNITS:
        issues.append("Units must match the declared SI input reference exactly")
    provenance = data.get("provenance")
    for section in PROVENANCE_SECTIONS:
        source = {}
        if isinstance(provenance, dict):
            source = provenance.get(section, {})
        if not _valid_provenance(source):
            issues.append(f"provenance.{section} needs a synthetic source and explicit validity")

    # physical and numerical inputs are checked by building them

    try:
        _add_reactor_issues(data, issues)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        issues.append(f"Required reactor/transport/chemistry input: {error}")
    try:
        _check_recipe_and_grids(data)
    except (KeyError, TypeError, ValueError) as error:
        issues.append(f"Required recipe/numerical input: {error}")

    # the zno film mapping only belongs to the synthetic-zno example

    if "film" not in data:
        issues.append("film is required; use null when no supported thickness mapping exists")
    elif data["film"] is not None and data["film"] != ZNO_FILM:
        issues.append("Only the fixed conditional ZnO mapping is supported; otherwise film must be null")
    if data.get("film") is not None and (data.get("id") != "synthetic-zno" or species != ZNO_SPECIES):
        issues.append("The ZnO mapping cannot be transferred to another process")
    return issues


# turning checked inputs into a runnable recipe

def prepare_inputs(data):
    """validate before constructing flow, chemistry or a recipe for calculation."""

    data = deepcopy(data)
    issues = input_issues(data)
    if issues:
        raise ValueError("; ".join(issues))

    # recipe ratios are in residence times of the well-mixed (one-cell) reactor

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
    durations = [segment.duration for segment in segments]
    precursor = sum(s.duration*(s.inlet_a+s.inlet_b) for s in segments)
    report["flow"] = dict(residence_s=residence, pressure_pa=pressure.tolist(),
                          mean_velocity_m_s=velocity.tolist(),
                          segment_duration_s=durations,
                          precursor_moles=precursor)
    if data["film"]:
        report["film_status"] = "Conditional synthetic ZnO equivalent"
    else:
        report["film_status"] = "Unavailable; surface turnover only"
    return report
