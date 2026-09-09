#!/usr/bin/env python3
"""Reproducible, bounded Benchmark A numerical gate. No experimental fitting."""

import argparse
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

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"results/phase2"
FIG = ROOT/"figures/phase2"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(coarse, fine):
    coarse_arrays, fine_arrays = coarse["arrays"], fine["arrays"]
    cells = coarse_arrays["xi"].size
    return dict(
        coverage=float(np.max(np.abs(
            coarse_arrays["theta"][-1] - restrict_uniform(fine_arrays["theta"][-1], cells)))),
        uptake=float(abs(coarse_arrays["captured"][-1] - fine_arrays["captured"][-1])
                     / abs(fine_arrays["captured"][-1])),
        front=abs(front_position(coarse_arrays["xi"], coarse_arrays["theta"][-1])
                  - front_position(fine_arrays["xi"], fine_arrays["theta"][-1])),
    )


def load_cached_case(stem, cache_key):
    """Reuse a matching case only after checking every recorded artifact hash."""
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
    """Numerical diagnostics at the retained pulse/purge readouts."""
    denominator = arrays["entered"]
    positive = denominator > 0
    return dict(
        ledger_relative=float(np.max(np.abs(arrays["ledger_error"][positive]) / denominator[positive])),
        zero_inventory_residual=(float(np.max(np.abs(arrays["ledger_error"][~positive])))
                                 if np.any(~positive) else 0.),
        bound_violation=max(0., -float(arrays["x"].min()), float(arrays["x"].max()) - 1,
                            -float(arrays["theta"].min()), float(arrays["theta"].max()) - 1),
        state_carryover_exact=solver_status[0]["end_state"] == solver_status[1]["start_state"],
        front_final=front_position(arrays["xi"], arrays["theta"][-1]),
        uptake_final=float(arrays["captured"][-1]),
        entered_final=float(arrays["entered"][-1]),
        escaped_final=float(arrays["escaped"][-1]),
        gas_final=float(arrays["gas"][-1]),
        solver_nfev=sum(segment["nfev"] for segment in solver_status),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Reuse cases only when solver sources, configs, scales, and settings match")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    benchmark_path = ROOT/"config/benchmarks/benchmark-a.json"
    recipes_path = ROOT/"config/synthetic/phase2-recipes.json"
    registry = ParameterRegistry.load(benchmark_path)
    values = registry.resolve({"pe": "1", "da": "1", "gamma": "1"})
    groups = DimensionlessGroups(**values)
    recipes = ParameterRegistry.load(recipes_path).resolve({
        **{n: "1" for n in ("pulse_short", "pulse_main", "pulse_long", "purge_tau", "extent", "initial_spacing")},
        "scale_length": "m", "scale_diffusivity": "m^2 s^-1", "scale_concentration": "mol m^-3",
        "scale_area": "m^2", "scale_area_ratio": "m^-1"})
    scales = MathematicalScales(**{k.removeprefix("scale_"): v for k, v in recipes.items() if k.startswith("scale_")})
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/"src/ald_twin").glob("*.py"))}
    for p in [benchmark_path, recipes_path, ROOT/"docs/phase2-plan.md",
              ROOT/"docs/phase2-refinement-amendment.md", ROOT/"requirements-lock.txt"]:
        inputs[str(p.relative_to(ROOT))] = sha(p)
    cases, checks = {}, []

    def check(name, measured, limit, category):
        checks.append(dict(name=name, measured=float(measured), limit=float(limit),
                           passed=bool(np.isfinite(measured) and measured <= limit), category=category))

    def run(name, *, spacing, pulse, extent=2., method="Radau", tight=False,
            chosen_scales=scales, purge=recipes["purge_tau"]):
        cells = round(extent/spacing)
        if not np.isclose(cells*spacing, extent, rtol=0, atol=1e-12):
            raise ValueError("Grid must partition the full extent")
        options = SolverOptions(method, 1e-9 if tight else 1e-8,
                                1e-11 if tight else 1e-10, .0005 if tight else .001)
        sampled = [0., pulse/4, pulse, pulse+purge/2, pulse+purge]
        config = dict(groups=asdict(groups), extent=extent, cells=cells,
            pulse_tau=pulse, purge_tau=purge, scales=asdict(chosen_scales),
            solver=asdict(options), output_tau=sampled, inputs=inputs)
        key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        stem = OUT/name
        summary_path = OUT/(name+"-metrics.json")
        cached = load_cached_case(stem, key) if args.resume else None
        if cached is not None:
            arrays, summary = cached
            print(f"reuse {name}", flush=True)
        else:
            print(f"solve {name}: N={cells}, {method}, tight={tight}", flush=True)
            start = time.monotonic()
            result = solve_dimensionless(groups, extent=extent, cells=cells,
                pulse_tau=pulse, purge_tau=purge, scales=chosen_scales,
                options=options, output_tau=sampled,
                provenance_id=registry.identifier+"/phase2-synthetic-recipes/"+name)
            result.save(stem)
            arrays = result.arrays()
            summary = dict(name=name, cache_key=key, configuration=config,
                elapsed_seconds=time.monotonic()-start,
                **case_metrics(arrays, result.raw.solver_status),
                dnum_ratio=groups.pe*spacing/2,
                artifact_sha256={p.name: sha(p) for p in [Path(str(stem)+suffix) for suffix in (
                    ".npz", ".json", "-synthetic-representative.npz", "-synthetic-representative.json")]})
            write_json(summary_path, summary)
            print(f"done {name}: {summary['elapsed_seconds']:.1f}s, front={summary['front_final']:.6g}, ledger={summary['ledger_relative']:.3g}", flush=True)
        cases[name] = dict(arrays=arrays, summary=summary)
        check(name+" ledger", summary["ledger_relative"], 1e-8, "conservation")
        check(name+" zero-inventory residual", summary["zero_inventory_residual"], 1e-10, "conservation")
        check(name+" bounds", summary["bound_violation"], 1e-8, "bounds")
        check(name+" state carryover", 0 if summary["state_carryover_exact"] else 1, 0, "segmentation")
        check(name+" numerical diffusion", summary["dnum_ratio"], .05, "numerical diffusion")
        return cases[name]

    # Accept the cheaper refinement domain only after explicit extension checks.
    domain_checks = {}
    for label in ("main", "long"):
        small = run(label+"-domain2", spacing=recipes["initial_spacing"], pulse=recipes["pulse_"+label])
        large = run(label+"-domain10", spacing=recipes["initial_spacing"], pulse=recipes["pulse_"+label], extent=10.)
        a, b = small["arrays"], large["arrays"]
        count = a["xi"].size
        error = dict(x=float(np.max(np.abs(a["x"]-b["x"][:, :count]))),
            coverage=float(np.max(np.abs(a["theta"]-b["theta"][:, :count]))),
            uptake=float(abs(a["captured"][-1]-b["captured"][-1])/abs(b["captured"][-1])),
            front=abs(small["summary"]["front_final"]-large["summary"]["front_final"]))
        domain_checks[label] = error
        for key, value in error.items():
            check(label+" extent 2 versus 10 "+key, value, 1e-5, "domain truncation")
        write_json(OUT/"refinement-domain-checks.json", domain_checks)
        if any(v > 1e-5 for v in error.values()):
            raise RuntimeError("Extent 2 not accepted: enlarge refinement domain; preserve thresholds")

    main_grids, spatial = [], []
    initial = recipes["initial_spacing"]
    for level in range(7):
        h = initial/2**level
        current = run(f"main-h{level}", spacing=h, pulse=recipes["pulse_main"])
        main_grids.append(current)
        if level:
            error = compare(main_grids[-2], current)
            spatial.append(dict(level=level, spacing=h, **error))
            write_json(OUT/"spatial-attempts.json", spatial)
            print(f"spatial {level}: {error}", flush=True)
        if level < 2 or not all(v <= 1e-3 for k, v in spatial[-1].items() if k in ("coverage", "uptake", "front")):
            continue
        if not all(spatial[-1][k] < spatial[-2][k] for k in ("coverage", "uptake", "front")):
            continue
        long_coarse = run(f"long-h{level-1}", spacing=2*h, pulse=recipes["pulse_long"])
        long_fine = run(f"long-h{level}", spacing=h, pulse=recipes["pulse_long"])
        long_error = compare(long_coarse, long_fine)
        write_json(OUT/f"long-comparison-h{level}.json", long_error)
        print(f"long spatial {level}: {long_error}", flush=True)
        if all(v <= 1e-3 for v in long_error.values()):
            break
    else:
        raise RuntimeError("Spatial study did not converge within seven predeclared halved grids; retained all attempts")
    for metric in ("coverage", "uptake", "front"):
        check("main spatial "+metric, spatial[-1][metric], 1e-3, "spatial convergence")
        check("main decreasing "+metric, 0 if spatial[-1][metric] < spatial[-2][metric] else 1, 0, "spatial convergence")
        check("long spatial "+metric, long_error[metric], 1e-3, "spatial convergence")

    radau_tight = run("main-radau-tight", spacing=h, pulse=recipes["pulse_main"], tight=True)
    bdf_base = run("main-bdf", spacing=h, pulse=recipes["pulse_main"], method="BDF")
    bdf_tight = run("main-bdf-tight", spacing=h, pulse=recipes["pulse_main"], method="BDF", tight=True)
    temporal = {}
    for name, a, b in [("Radau refinement", current, radau_tight),
                       ("BDF refinement", bdf_base, bdf_tight),
                       ("tight Radau-BDF", radau_tight, bdf_tight)]:
        temporal[name] = compare(a, b)
        check(name+" coverage", temporal[name]["coverage"], 1e-5, "temporal convergence")
        check(name+" uptake", temporal[name]["uptake"], 1e-5, "temporal convergence")
    short = run("short-final", spacing=h, pulse=recipes["pulse_short"])
    extension = run("main-extent20", spacing=initial, pulse=recipes["pulse_main"], extent=20.)
    prefix = cases["main-domain10"]["arrays"]["xi"] <= 1.
    count = int(prefix.sum())
    truncation = float(np.max(np.abs(cases["main-domain10"]["arrays"]["theta"][-1, :count]-extension["arrays"]["theta"][-1, :count])))
    check("10L versus 20L coverage on [0,L]", truncation, 1e-4, "domain truncation")

    inv_args = dict(spacing=initial, pulse=.002, purge=.003, extent=2.)
    inv_a = run("invariance-unit", **inv_args)
    alternate = MathematicalScales(.13, .004, .7, .002, 17.)
    inv_b = run("invariance-alternate", chosen_scales=alternate, **inv_args)
    invariance = {}
    for name, array in inv_a["arrays"].items():
        other = inv_b["arrays"][name]
        if array.shape != other.shape:
            raise ValueError("Representative invariance comparison requires matching sample shapes")
        invariance[name] = float(np.max(np.abs(array-other)))
        check("representative invariance "+name, invariance[name], 1e-7, "convention mapping")
    for i, chosen in enumerate((scales, alternate)):
        r, s = representative(groups, chosen, extent=10, cells=100)
        a = r.reactive_perimeter/r.area
        recovered = [r.velocity*chosen.length/r.diffusivity,
                     a*s.capture_velocity*chosen.length**2/r.diffusivity,
                     chosen.concentration/(a*s.capacity)]
        for name, value, expected in zip(("Pe", "Da", "gamma"), recovered, (groups.pe, groups.da, groups.gamma)):
            check(f"representative {i} recovers {name}", abs(value-expected)/expected, 1e-12, "convention mapping")

    limitations = [
        "Formulation reproduction only; no exact published-curve or experimental validation claim.",
        "Pulse/readout scenarios are synthetic; published metadata and physical mapping remain unresolved.",
        "Main and longest scenarios have explicit spatial comparisons; short scenario uses their accepted spacing without a separate spatial study.",
        "Temporal study uses the main scenario. Extent 2 versus 10 checks both main and long cases on [0,2]; 10 versus 20 checks main on [0,1], all at initial spacing.",
        "Bounds and conservation are measured at retained outputs; Radau/BDF share the spatial discretization.",
        "Original full text was not newly retrieved; reported groups and equations follow the prior audit preserved in the freeze.",
        "Phase 3 and all physical fitting remain unstarted."]
    report = dict(phase=2, gate="PASS" if all(c["passed"] for c in checks) else "FAIL",
        claim="Documented dimensionless formulation reproduced with numerically checked synthetic pulse scenarios",
        groups=asdict(groups), beta0_metadata=.01, final_spacing=h, final_level=level,
        checks=checks, cases={k: v["summary"] for k, v in cases.items()},
        spatial_attempts=spatial, long_spatial=long_error, temporal=temporal,
        truncation=truncation, refinement_domain_checks=domain_checks, refinement_extent=2.,
        invariance=invariance, limitations=limitations,
        inputs_sha256=inputs, runner_sha256=sha(Path(__file__)))
    write_report(report, cases)
    figures(cases, spatial, temporal, truncation, level)
    print(json.dumps({k: report[k] for k in ("gate", "final_spacing", "long_spatial", "temporal", "truncation", "invariance")}, indent=2), flush=True)
    if report["gate"] != "PASS":
        raise SystemExit(1)


def write_report(report, cases):
    """Write the gate, its limits and the conservation table without solving cases."""
    write_json(OUT / "gate.json", report)
    groups = report["groups"]
    spacing = report["final_spacing"]
    checks = report["checks"]
    lines = ["# Phase 2 numerical gate", "", f"**{report['gate']} — dimensionless formulation reproduction only.**", "",
        f"Pe={groups['pe']:g}, Da={groups['da']:g}, gamma={groups['gamma']:g}; beta0=0.01 is metadata already included in Da.", "",
        f"Accepted delta-xi={spacing:g}, {round(2/spacing)} cells over [0,2]. {len(checks)} numerical checks.", "",
        "| Check | Measured | Limit | Result |", "|---|---:|---:|---|"]
    lines += [f"| {c['name']} | {c['measured']:.9g} | {c['limit']:.3g} | {'PASS' if c['passed'] else 'FAIL'} |" for c in checks]
    lines += ["", "## Limits", ""]+["- "+s for s in report["limitations"]]
    (OUT/"gate.md").write_text("\n".join(lines)+"\n")
    import csv
    with (OUT/"conservation.csv").open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["case", "tau", "gas", "captured", "entered", "escaped", "ledger_error", "normalization"])
        for name, case in cases.items():
            arrays = case["arrays"]
            for j, tau in enumerate(arrays["tau"]):
                writer.writerow([name, tau]+[arrays[k][j] for k in ("gas", "captured", "entered", "escaped", "ledger_error")]+["N/(A*L*c0*)"])


def figures(cases, spatial, temporal, truncation, level):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    for key, label in [("short-final", "0.005"), (f"main-h{level}", "0.010"), (f"long-h{level}", "0.015")]:
        arrays = cases[key]["arrays"]
        axes[0].plot(arrays["xi"], arrays["theta"][-1], label=f"pulse tau = {label}")
        axes[1].plot(arrays["xi"], arrays["x"][-1], label=f"pulse tau = {label}")
    for ax, ylabel in zip(axes, ["Occupied capacity theta", "Normalized gas x"]):
        ax.set(xlim=(0, 2), xlabel="xi = z/L", ylabel=ylabel)
        ax.grid(alpha=.2)
        ax.legend(frameon=False)
    fig.suptitle("Synthetic pulse scenarios at Pe=65, Da=1550, gamma=2.5\nEnd of purge (delta-tau=0.010); no published-curve match claimed")
    fig.savefig(FIG/"synthetic-profiles.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    for metric, label in [("coverage", "max coverage"), ("uptake", "relative uptake"), ("front", "front / L")]:
        axes[0].loglog([s["spacing"] for s in spatial], [s[metric] for s in spatial], "o-", label=label)
    axes[0].axhline(1e-3, color="black", ls="--", label="acceptance limit")
    axes[0].invert_xaxis()
    from matplotlib.ticker import NullFormatter
    tick_locations = [s["spacing"] for s in spatial]
    axes[0].set_xticks(tick_locations, [f"{v:.2e}" for v in tick_locations])
    axes[0].xaxis.set_minor_formatter(NullFormatter())
    axes[0].tick_params(axis="x", labelsize=9)
    axes[0].set(xlabel="Fine-grid delta-xi", ylabel="Difference from previous grid", title="Main scenario spatial refinement")
    axes[0].legend(frameon=False)
    names = list(temporal)
    axes[1].bar(np.arange(len(names)), [temporal[n]["coverage"] for n in names], color=["#20639b", "#3caea3", "#ed553b"])
    axes[1].axhline(1e-5, color="black", ls="--", label="acceptance limit")
    axes[1].set_yscale("log")
    axes[1].set_ylim(1e-12, 3e-5)
    axes[1].set_xticks(np.arange(len(names)), ["Radau\nrefinement", "BDF\nrefinement", "Tight\nRadau/BDF"])
    axes[1].set(ylabel="Maximum coverage difference", title="Main scenario time integration")
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle("Numerical convergence at the frozen dimensionless groups")
    fig.savefig(FIG/"convergence.png", dpi=180)
    plt.close(fig)

    arrays = cases[f"main-h{level}"]["arrays"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    for key, label in [("entered", "Entered"), ("gas", "Gas"), ("captured", "Captured"), ("escaped", "Boundary escape")]:
        axes[0].plot(arrays["tau"], arrays[key], "o-", label=label)
    axes[0].axvline(.010, ls="--", color="grey", label="Exposure / purge switch")
    axes[0].set(xlabel="tau = t D/L²", ylabel="N / (A* L* c0*)", title="Shared-flux accounting at retained readouts")
    axes[0].legend(frameon=False, fontsize=9)
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
    fig.savefig(FIG/"accounting-and-truncation.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
