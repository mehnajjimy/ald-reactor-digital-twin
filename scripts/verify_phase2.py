#!/usr/bin/env python3
"""Reproducible, bounded Benchmark A numerical gate. No experimental fitting."""

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ald_twin.configuration import ParameterRegistry
from ald_twin.dimensionless import (DimensionlessGroups, MathematicalScales,
                                   representative, solve_dimensionless)
from ald_twin.numerics import SolverOptions
from ald_twin.verification import front_position, restrict_uniform

# where inputs are read and results and figures are written
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"results/phase2"
FIG = ROOT/"figures/phase2"

# units each synthetic recipe entry must be declared with
RECIPE_UNITS = {
    "pulse_short": "1", "pulse_main": "1", "pulse_long": "1", "purge_tau": "1",
    "extent": "1", "initial_spacing": "1",
    "scale_length": "m", "scale_diffusivity": "m^2 s^-1", "scale_concentration": "mol m^-3",
    "scale_area": "m^2", "scale_area_ratio": "m^-1"}

# solver tolerances: normal and tight runs (max_step is in tau)
NORMAL_RTOL, NORMAL_ATOL, NORMAL_MAX_STEP = 1e-8, 1e-10, .001
TIGHT_RTOL, TIGHT_ATOL, TIGHT_MAX_STEP = 1e-9, 1e-11, .0005

# domain lengths in units of L, and how exactly the cells must fill a domain
REFINEMENT_EXTENT = 2.
DOMAIN_CHECK_EXTENT = 10.
TRUNCATION_CHECK_EXTENT = 20.
GRID_PARTITION_ATOL = 1e-12

# pass limits for each numerical check
LEDGER_LIMIT = 1e-8
ZERO_INVENTORY_LIMIT = 1e-10
BOUND_LIMIT = 1e-8
NUMERICAL_DIFFUSION_LIMIT = .05
DOMAIN_LIMIT = 1e-5
SPATIAL_LIMIT = 1e-3
TEMPORAL_LIMIT = 1e-5
TRUNCATION_LIMIT = 1e-4
INVARIANCE_LIMIT = 1e-7
RECOVERY_LIMIT = 1e-12

# spatial study: at most this many halved grids, compared on these metrics
MAX_GRID_LEVELS = 7
SPATIAL_METRICS = ("coverage", "uptake", "front")

# invariance study: a short synthetic pulse and a second, unrelated set of scales
INVARIANCE_PULSE = .002
INVARIANCE_PURGE = .003
ALTERNATE_SCALES = (.13, .004, .7, .002, 17.)

# representative used to recover the groups from SI coefficients
RECOVERY_EXTENT = 10
RECOVERY_CELLS = 100

# beta0 is metadata only, it is already inside Da
BETA0_METADATA = .01

# figure layout
FIGURE_SIZE = (11, 4.5)
FIGURE_DPI = 180

# limitations written into gate.json and gate.md
LIMITATIONS = [
    "Formulation reproduction only; no exact published-curve or experimental validation claim.",
    "Pulse/readout scenarios are synthetic; published metadata and physical mapping remain unresolved.",
    "Main and longest scenarios have explicit spatial comparisons; short scenario uses their accepted spacing without a separate spatial study.",
    "Temporal study uses the main scenario. Extent 2 versus 10 checks both main and long cases on [0,2]; 10 versus 20 checks main on [0,1], all at initial spacing.",
    "Bounds and conservation are measured at retained outputs; Radau/BDF share the spatial discretization.",
    "Original full text was not newly retrieved; reported groups and equations follow the prior audit preserved in the freeze.",
    "Phase 3 and all physical fitting remain unstarted."]


# small file helpers

def write_json(path, value):
    """write value as indented json with a trailing newline."""
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def sha(path):
    """sha-256 hex digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# case comparison and diagnostics

def compare(coarse, fine):
    """final coverage, uptake and front differences between two grids."""
    coarse_arrays = coarse["arrays"]
    fine_arrays = fine["arrays"]
    cells = coarse_arrays["xi"].size

    fine_theta_on_coarse = restrict_uniform(fine_arrays["theta"][-1], cells)
    coverage = float(np.max(np.abs(coarse_arrays["theta"][-1] - fine_theta_on_coarse)))

    captured_difference = abs(coarse_arrays["captured"][-1] - fine_arrays["captured"][-1])
    uptake = float(captured_difference / abs(fine_arrays["captured"][-1]))

    coarse_front = front_position(coarse_arrays["xi"], coarse_arrays["theta"][-1])
    fine_front = front_position(fine_arrays["xi"], fine_arrays["theta"][-1])
    front = abs(coarse_front - fine_front)
    return dict(coverage=coverage, uptake=uptake, front=front)


def load_cached_case(stem, cache_key):
    """reuse a matching case only after checking every recorded artifact hash."""
    summary_path = Path(str(stem) + "-metrics.json")
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text())
    if not summary or summary["cache_key"] != cache_key:
        return None
    for filename, digest in summary["artifact_sha256"].items():
        if sha(stem.parent / filename) != digest:
            raise ValueError(f"Cached artifact changed: {filename}")
    with np.load(str(stem) + ".npz") as saved:
        arrays = {name: saved[name] for name in saved.files}
    return arrays, summary


def case_metrics(arrays, solver_status):
    """numerical diagnostics at the retained pulse/purge readouts."""
    # ledger error relative to what entered, and absolute where nothing entered yet
    entered = arrays["entered"]
    positive = entered > 0
    ledger_error = arrays["ledger_error"]
    ledger_relative = float(np.max(np.abs(ledger_error[positive]) / entered[positive]))
    if np.any(~positive):
        zero_inventory_residual = float(np.max(np.abs(ledger_error[~positive])))
    else:
        zero_inventory_residual = 0.

    # how far normalized gas x or coverage theta goes outside [0, 1]
    bound_violation = max(0., -float(arrays["x"].min()), float(arrays["x"].max()) - 1,
                          -float(arrays["theta"].min()), float(arrays["theta"].max()) - 1)

    return dict(
        ledger_relative=ledger_relative,
        zero_inventory_residual=zero_inventory_residual,
        bound_violation=bound_violation,
        state_carryover_exact=solver_status[0]["end_state"] == solver_status[1]["start_state"],
        front_final=front_position(arrays["xi"], arrays["theta"][-1]),
        uptake_final=float(arrays["captured"][-1]),
        entered_final=float(arrays["entered"][-1]),
        escaped_final=float(arrays["escaped"][-1]),
        gas_final=float(arrays["gas"][-1]),
        solver_nfev=sum(segment["nfev"] for segment in solver_status),
    )


# the study: runs cases, caches them and records every check

class Phase2Study:
    """shared state for one gate run: inputs, solved cases and check results."""

    def __init__(self, resume, registry, groups, recipes, scales, inputs):
        """keep the frozen inputs and start with no cases or checks."""
        self.resume = resume
        self.registry = registry
        self.groups = groups
        self.recipes = recipes
        self.scales = scales
        self.inputs = inputs
        self.cases = {}
        self.checks = []

    def check(self, name, measured, limit, category):
        """record one pass/fail check. non-finite measurements fail."""
        measured_value = float(measured)
        limit_value = float(limit)
        passed = bool(np.isfinite(measured) and measured <= limit)
        self.checks.append(dict(name=name, measured=measured_value, limit=limit_value,
                                passed=passed, category=category))

    def run(self, name, *, spacing, pulse, extent=REFINEMENT_EXTENT, method="Radau",
            tight=False, chosen_scales=None, purge=None):
        """solve one case (or reuse it with --resume) and record its checks."""
        if chosen_scales is None:
            chosen_scales = self.scales
        if purge is None:
            purge = self.recipes["purge_tau"]

        # grid and solver settings
        cells = round(extent/spacing)
        if not np.isclose(cells*spacing, extent, rtol=0, atol=GRID_PARTITION_ATOL):
            raise ValueError("Grid must partition the full extent")
        if tight:
            options = SolverOptions(method, TIGHT_RTOL, TIGHT_ATOL, TIGHT_MAX_STEP)
        else:
            options = SolverOptions(method, NORMAL_RTOL, NORMAL_ATOL, NORMAL_MAX_STEP)
        sampled = [0., pulse/4, pulse, pulse+purge/2, pulse+purge]

        # everything that decides the result goes into the cache key
        config = dict(groups=asdict(self.groups), extent=extent, cells=cells,
            pulse_tau=pulse, purge_tau=purge, scales=asdict(chosen_scales),
            solver=asdict(options), output_tau=sampled, inputs=self.inputs)
        key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        stem = OUT/name
        summary_path = OUT/(name+"-metrics.json")

        cached = None
        if self.resume:
            cached = load_cached_case(stem, key)
        if cached is not None:
            arrays, summary = cached
            print(f"reuse {name}", flush=True)
        else:
            print(f"solve {name}: N={cells}, {method}, tight={tight}", flush=True)
            start = time.monotonic()
            result = solve_dimensionless(self.groups, extent=extent, cells=cells,
                pulse_tau=pulse, purge_tau=purge, scales=chosen_scales,
                options=options, output_tau=sampled,
                provenance_id=self.registry.identifier+"/phase2-synthetic-recipes/"+name)
            result.save(stem)
            arrays = result.arrays()
            # elapsed time stops before the artifacts are hashed
            elapsed_seconds = time.monotonic()-start
            artifact_sha256 = {}
            for suffix in (".npz", ".json", "-synthetic-representative.npz",
                           "-synthetic-representative.json"):
                path = Path(str(stem)+suffix)
                artifact_sha256[path.name] = sha(path)
            summary = dict(name=name, cache_key=key, configuration=config,
                elapsed_seconds=elapsed_seconds,
                **case_metrics(arrays, result.raw.solver_status),
                dnum_ratio=self.groups.pe*spacing/2,
                artifact_sha256=artifact_sha256)
            write_json(summary_path, summary)
            print(f"done {name}: {summary['elapsed_seconds']:.1f}s, front={summary['front_final']:.6g}, ledger={summary['ledger_relative']:.3g}", flush=True)
        self.cases[name] = dict(arrays=arrays, summary=summary)

        # per-case checks
        self.check(name+" ledger", summary["ledger_relative"], LEDGER_LIMIT, "conservation")
        self.check(name+" zero-inventory residual", summary["zero_inventory_residual"],
                   ZERO_INVENTORY_LIMIT, "conservation")
        self.check(name+" bounds", summary["bound_violation"], BOUND_LIMIT, "bounds")
        carryover_failures = 0 if summary["state_carryover_exact"] else 1
        self.check(name+" state carryover", carryover_failures, 0, "segmentation")
        self.check(name+" numerical diffusion", summary["dnum_ratio"],
                   NUMERICAL_DIFFUSION_LIMIT, "numerical diffusion")
        return self.cases[name]


# study steps, run in this order by main

def load_study(resume):
    """load the frozen groups, recipes and scales and hash every input file."""
    benchmark_path = ROOT/"config/benchmarks/benchmark-a.json"
    recipes_path = ROOT/"config/synthetic/phase2-recipes.json"
    registry = ParameterRegistry.load(benchmark_path)
    values = registry.resolve({"pe": "1", "da": "1", "gamma": "1"})
    groups = DimensionlessGroups(**values)
    recipes = ParameterRegistry.load(recipes_path).resolve(RECIPE_UNITS)
    scales = MathematicalScales(
        length=recipes["scale_length"], diffusivity=recipes["scale_diffusivity"],
        concentration=recipes["scale_concentration"], area=recipes["scale_area"],
        area_ratio=recipes["scale_area_ratio"])

    inputs = {}
    for path in sorted((ROOT/"src/ald_twin").glob("*.py")):
        inputs[str(path.relative_to(ROOT))] = sha(path)
    for path in [benchmark_path, recipes_path, ROOT/"docs/phase2-plan.md",
                 ROOT/"docs/phase2-refinement-amendment.md", ROOT/"requirements-lock.txt"]:
        inputs[str(path.relative_to(ROOT))] = sha(path)
    return Phase2Study(resume, registry, groups, recipes, scales, inputs)


def domain_study(study):
    """accept the cheaper refinement domain only after explicit extension checks."""
    recipes = study.recipes
    domain_checks = {}
    for label in ("main", "long"):
        small = study.run(label+"-domain2", spacing=recipes["initial_spacing"],
                          pulse=recipes["pulse_"+label])
        large = study.run(label+"-domain10", spacing=recipes["initial_spacing"],
                          pulse=recipes["pulse_"+label], extent=DOMAIN_CHECK_EXTENT)
        a = small["arrays"]
        b = large["arrays"]
        count = a["xi"].size
        error = dict(x=float(np.max(np.abs(a["x"]-b["x"][:, :count]))),
            coverage=float(np.max(np.abs(a["theta"]-b["theta"][:, :count]))),
            uptake=float(abs(a["captured"][-1]-b["captured"][-1])/abs(b["captured"][-1])),
            front=abs(small["summary"]["front_final"]-large["summary"]["front_final"]))
        domain_checks[label] = error
        for metric, value in error.items():
            study.check(label+" extent 2 versus 10 "+metric, value, DOMAIN_LIMIT, "domain truncation")
        write_json(OUT/"refinement-domain-checks.json", domain_checks)
        for value in error.values():
            if value > DOMAIN_LIMIT:
                raise RuntimeError("Extent 2 not accepted: enlarge refinement domain; preserve thresholds")
    return domain_checks


def _spatial_converged(spatial):
    """true when the newest grid step meets every spatial limit."""
    for metric in SPATIAL_METRICS:
        if not spatial[-1][metric] <= SPATIAL_LIMIT:
            return False
    return True


def _spatial_decreasing(spatial):
    """true when every spatial metric shrank since the previous grid step."""
    for metric in SPATIAL_METRICS:
        if not spatial[-1][metric] < spatial[-2][metric]:
            return False
    return True


def spatial_study(study):
    """halve the grid until main and long scenarios both converge.

    returns the attempts, the long comparison, the final level and spacing and
    the finest main case.
    """
    recipes = study.recipes
    initial = recipes["initial_spacing"]
    main_grids = []
    spatial = []
    for level in range(MAX_GRID_LEVELS):
        h = initial/2**level
        current = study.run(f"main-h{level}", spacing=h, pulse=recipes["pulse_main"])
        main_grids.append(current)
        if level:
            error = compare(main_grids[-2], current)
            spatial.append(dict(level=level, spacing=h, **error))
            write_json(OUT/"spatial-attempts.json", spatial)
            print(f"spatial {level}: {error}", flush=True)

        # need two comparisons, both under the limit and still shrinking
        if level < 2 or not _spatial_converged(spatial):
            continue
        if not _spatial_decreasing(spatial):
            continue

        # confirm with the long pulse on the same pair of grids
        long_coarse = study.run(f"long-h{level-1}", spacing=2*h, pulse=recipes["pulse_long"])
        long_fine = study.run(f"long-h{level}", spacing=h, pulse=recipes["pulse_long"])
        long_error = compare(long_coarse, long_fine)
        write_json(OUT/f"long-comparison-h{level}.json", long_error)
        print(f"long spatial {level}: {long_error}", flush=True)
        long_converged = True
        for value in long_error.values():
            if not value <= SPATIAL_LIMIT:
                long_converged = False
        if long_converged:
            break
    else:
        raise RuntimeError("Spatial study did not converge within seven predeclared halved grids; retained all attempts")

    for metric in SPATIAL_METRICS:
        study.check("main spatial "+metric, spatial[-1][metric], SPATIAL_LIMIT, "spatial convergence")
        not_decreasing = 0 if spatial[-1][metric] < spatial[-2][metric] else 1
        study.check("main decreasing "+metric, not_decreasing, 0, "spatial convergence")
        study.check("long spatial "+metric, long_error[metric], SPATIAL_LIMIT, "spatial convergence")
    return spatial, long_error, level, h, current


def temporal_study(study, h, current):
    """compare Radau and BDF at normal and tight tolerances on the final grid."""
    pulse = study.recipes["pulse_main"]
    radau_tight = study.run("main-radau-tight", spacing=h, pulse=pulse, tight=True)
    bdf_base = study.run("main-bdf", spacing=h, pulse=pulse, method="BDF")
    bdf_tight = study.run("main-bdf-tight", spacing=h, pulse=pulse, method="BDF", tight=True)
    temporal = {}
    for name, a, b in [("Radau refinement", current, radau_tight),
                       ("BDF refinement", bdf_base, bdf_tight),
                       ("tight Radau-BDF", radau_tight, bdf_tight)]:
        temporal[name] = compare(a, b)
        study.check(name+" coverage", temporal[name]["coverage"], TEMPORAL_LIMIT, "temporal convergence")
        study.check(name+" uptake", temporal[name]["uptake"], TEMPORAL_LIMIT, "temporal convergence")
    return temporal


def truncation_study(study, h):
    """run the short pulse, then compare extent 10 and 20 coverage on [0, L]."""
    recipes = study.recipes
    study.run("short-final", spacing=h, pulse=recipes["pulse_short"])
    extension = study.run("main-extent20", spacing=recipes["initial_spacing"],
                          pulse=recipes["pulse_main"], extent=TRUNCATION_CHECK_EXTENT)
    domain10 = study.cases["main-domain10"]["arrays"]
    prefix = domain10["xi"] <= 1.
    count = int(prefix.sum())
    difference = domain10["theta"][-1, :count]-extension["arrays"]["theta"][-1, :count]
    truncation = float(np.max(np.abs(difference)))
    study.check("10L versus 20L coverage on [0,L]", truncation, TRUNCATION_LIMIT, "domain truncation")
    return truncation


def invariance_study(study):
    """check two unrelated scale choices give the same normalized solution."""
    inv_args = dict(spacing=study.recipes["initial_spacing"], pulse=INVARIANCE_PULSE,
                    purge=INVARIANCE_PURGE, extent=REFINEMENT_EXTENT)
    inv_a = study.run("invariance-unit", **inv_args)
    alternate = MathematicalScales(*ALTERNATE_SCALES)
    inv_b = study.run("invariance-alternate", chosen_scales=alternate, **inv_args)
    invariance = {}
    for name, array in inv_a["arrays"].items():
        other = inv_b["arrays"][name]
        if array.shape != other.shape:
            raise ValueError("Representative invariance comparison requires matching sample shapes")
        invariance[name] = float(np.max(np.abs(array-other)))
        study.check("representative invariance "+name, invariance[name], INVARIANCE_LIMIT, "convention mapping")
    return invariance, alternate


def recovery_study(study, alternate):
    """check Pe, Da and gamma come back out of each SI representative."""
    groups = study.groups
    for i, chosen in enumerate((study.scales, alternate)):
        r, s = representative(groups, chosen, extent=RECOVERY_EXTENT, cells=RECOVERY_CELLS)
        a = r.reactive_perimeter/r.area
        recovered = [r.velocity*chosen.length/r.diffusivity,
                     a*s.capture_velocity*chosen.length**2/r.diffusivity,
                     chosen.concentration/(a*s.capacity)]
        expected_values = (groups.pe, groups.da, groups.gamma)
        for name, value, expected in zip(("Pe", "Da", "gamma"), recovered, expected_values):
            study.check(f"representative {i} recovers {name}", abs(value-expected)/expected,
                        RECOVERY_LIMIT, "convention mapping")


def main():
    """run every study step, write the gate and figures, exit 1 on FAIL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Reuse cases only when solver sources, configs, scales, and settings match")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    study = load_study(args.resume)

    domain_checks = domain_study(study)
    spatial, long_error, level, h, current = spatial_study(study)
    temporal = temporal_study(study, h, current)
    truncation = truncation_study(study, h)
    invariance, alternate = invariance_study(study)
    recovery_study(study, alternate)

    # gate report
    checks = study.checks
    gate = "PASS"
    for entry in checks:
        if not entry["passed"]:
            gate = "FAIL"
    case_summaries = {}
    for name, case in study.cases.items():
        case_summaries[name] = case["summary"]
    report = dict(phase=2, gate=gate,
        claim="Documented dimensionless formulation reproduced with numerically checked synthetic pulse scenarios",
        groups=asdict(study.groups), beta0_metadata=BETA0_METADATA, final_spacing=h, final_level=level,
        checks=checks, cases=case_summaries,
        spatial_attempts=spatial, long_spatial=long_error, temporal=temporal,
        truncation=truncation, refinement_domain_checks=domain_checks,
        refinement_extent=REFINEMENT_EXTENT,
        invariance=invariance, limitations=list(LIMITATIONS),
        inputs_sha256=study.inputs, runner_sha256=sha(Path(__file__)))
    write_report(report, study.cases)
    figures(study.cases, spatial, temporal, truncation, level)

    printed = {}
    for key in ("gate", "final_spacing", "long_spatial", "temporal", "truncation", "invariance"):
        printed[key] = report[key]
    print(json.dumps(printed, indent=2), flush=True)
    if report["gate"] != "PASS":
        raise SystemExit(1)


# report files

def write_report(report, cases):
    """write the gate, its limits and the conservation table without solving cases."""
    write_json(OUT / "gate.json", report)
    groups = report["groups"]
    spacing = report["final_spacing"]
    checks = report["checks"]

    # gate.md
    lines = ["# Phase 2 numerical gate", "", f"**{report['gate']} — dimensionless formulation reproduction only.**", "",
        f"Pe={groups['pe']:g}, Da={groups['da']:g}, gamma={groups['gamma']:g}; beta0=0.01 is metadata already included in Da.", "",
        f"Accepted delta-xi={spacing:g}, {round(REFINEMENT_EXTENT/spacing)} cells over [0,2]. {len(checks)} numerical checks.", "",
        "| Check | Measured | Limit | Result |", "|---|---:|---:|---|"]
    for c in checks:
        result = "PASS" if c["passed"] else "FAIL"
        lines.append(f"| {c['name']} | {c['measured']:.9g} | {c['limit']:.3g} | {result} |")
    lines += ["", "## Limits", ""]
    for limitation in report["limitations"]:
        lines.append("- "+limitation)
    (OUT/"gate.md").write_text("\n".join(lines)+"\n")

    # conservation.csv, one row per case and readout
    inventory_names = ("gas", "captured", "entered", "escaped", "ledger_error")
    with (OUT/"conservation.csv").open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["case", "tau", "gas", "captured", "entered", "escaped", "ledger_error", "normalization"])
        for name, case in cases.items():
            arrays = case["arrays"]
            for j, tau in enumerate(arrays["tau"]):
                row = [name, tau]
                for inventory in inventory_names:
                    row.append(arrays[inventory][j])
                row.append("N/(A*L*c0*)")
                writer.writerow(row)


# figures

def figures(cases, spatial, temporal, truncation, level):
    """save the profile, convergence and accounting figures under FIG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    _profiles_figure(plt, cases, level)
    _convergence_figure(plt, spatial, temporal)
    _accounting_figure(plt, cases, truncation, level)


def _profiles_figure(plt, cases, level):
    """end-of-purge coverage and gas profiles for the three pulse lengths."""
    fig, axes = plt.subplots(1, 2, figsize=FIGURE_SIZE, constrained_layout=True)
    for key, label in [("short-final", "0.005"), (f"main-h{level}", "0.010"), (f"long-h{level}", "0.015")]:
        arrays = cases[key]["arrays"]
        axes[0].plot(arrays["xi"], arrays["theta"][-1], label=f"pulse tau = {label}")
        axes[1].plot(arrays["xi"], arrays["x"][-1], label=f"pulse tau = {label}")
    for ax, ylabel in zip(axes, ["Occupied capacity theta", "Normalized gas x"]):
        ax.set(xlim=(0, 2), xlabel="xi = z/L", ylabel=ylabel)
        ax.grid(alpha=.2)
        ax.legend(frameon=False)
    fig.suptitle("Synthetic pulse scenarios at Pe=65, Da=1550, gamma=2.5\nEnd of purge (delta-tau=0.010); no published-curve match claimed")
    fig.savefig(FIG/"synthetic-profiles.png", dpi=FIGURE_DPI)
    plt.close(fig)


def _convergence_figure(plt, spatial, temporal):
    """spatial refinement differences and time-integration differences."""
    from matplotlib.ticker import NullFormatter
    fig, axes = plt.subplots(1, 2, figsize=FIGURE_SIZE, constrained_layout=True)

    # left: spatial refinement on log axes, finest grid on the right
    spacings = [s["spacing"] for s in spatial]
    for metric, label in [("coverage", "max coverage"), ("uptake", "relative uptake"), ("front", "front / L")]:
        axes[0].loglog(spacings, [s[metric] for s in spatial], "o-", label=label)
    axes[0].axhline(SPATIAL_LIMIT, color="black", ls="--", label="acceptance limit")
    axes[0].invert_xaxis()
    axes[0].set_xticks(spacings, [f"{v:.2e}" for v in spacings])
    axes[0].xaxis.set_minor_formatter(NullFormatter())
    axes[0].tick_params(axis="x", labelsize=9)
    axes[0].set(xlabel="Fine-grid delta-xi", ylabel="Difference from previous grid", title="Main scenario spatial refinement")
    axes[0].legend(frameon=False)

    # right: coverage difference for each temporal comparison
    names = list(temporal)
    positions = np.arange(len(names))
    coverages = [temporal[n]["coverage"] for n in names]
    axes[1].bar(positions, coverages, color=["#20639b", "#3caea3", "#ed553b"])
    axes[1].axhline(TEMPORAL_LIMIT, color="black", ls="--", label="acceptance limit")
    axes[1].set_yscale("log")
    axes[1].set_ylim(1e-12, 3e-5)
    axes[1].set_xticks(positions, ["Radau\nrefinement", "BDF\nrefinement", "Tight\nRadau/BDF"])
    axes[1].set(ylabel="Maximum coverage difference", title="Main scenario time integration")
    axes[1].legend(frameon=False)

    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle("Numerical convergence at the frozen dimensionless groups")
    fig.savefig(FIG/"convergence.png", dpi=FIGURE_DPI)
    plt.close(fig)


def _accounting_figure(plt, cases, truncation, level):
    """inventory accounting over time and the extent 10 versus 20 profiles."""
    arrays = cases[f"main-h{level}"]["arrays"]
    fig, axes = plt.subplots(1, 2, figsize=FIGURE_SIZE, constrained_layout=True)

    # left: shared-flux accounting at the retained readouts
    for key, label in [("entered", "Entered"), ("gas", "Gas"), ("captured", "Captured"), ("escaped", "Boundary escape")]:
        axes[0].plot(arrays["tau"], arrays[key], "o-", label=label)
    axes[0].axvline(.010, ls="--", color="grey", label="Exposure / purge switch")
    axes[0].set(xlabel="tau = t D/L²", ylabel="N / (A* L* c0*)", title="Shared-flux accounting at retained readouts")
    axes[0].legend(frameon=False, fontsize=9)

    # right: coverage on [0, 1] for extent 10 and extent 20
    a = cases["main-domain10"]["arrays"]
    b = cases["main-extent20"]["arrays"]
    mask = a["xi"] <= 1
    axes[1].plot(a["xi"][mask], a["theta"][-1, mask], label="Extent 10")
    axes[1].plot(b["xi"][:mask.sum()], b["theta"][-1, :mask.sum()], "--", label="Extent 20")
    axes[1].set(xlabel="xi", ylabel="Occupied capacity theta", title=f"Truncation on [0,1]: max difference {truncation:.2e}")
    axes[1].legend(frameon=False)

    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle("Main synthetic scenario: pulse 0.010, purge 0.010")
    fig.savefig(FIG/"accounting-and-truncation.png", dpi=FIGURE_DPI)
    plt.close(fig)


if __name__ == "__main__":
    main()
