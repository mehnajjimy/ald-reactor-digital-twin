"""scientific figures and a local read-only view of verified study records."""

import json
from pathlib import Path

import numpy as np

from .process_runner import check_sources, digest, saved_case
from .process_study import feasibility, write_json

# feasibility states, in the order used for colors, legend labels and cell text

STATES = ["fail", "pass", "unresolved", "unverified", "outside-screen"]
COLORS = ["#edc4ba", "#9bd2bd", "#efdb9e", "#e6ebf0", "#cdbede"]
LABELS = ["Fails constraints", "Passes constraints", "Near threshold", "Not verified", "Outside wall screen"]
CELL_TEXT = {"pass": "Pass", "fail": "Fail", "unresolved": "Near limit",
             "unverified": "Unverified", "outside-screen": "Outside screen"}

# figure settings and unit conversions

FIGURE_DPI = 170
RANGE_COLOR = "#1c6c91"
REFERENCE_COLOR = "#be533b"
EDGE_COLOR = "#283c50"
SELECTED_COLOR = "#116d50"
MS_PER_S = 1000
NMOL_PER_MOL = 1e9
PROFILE_POINTS = 100


# reading a finished study

def read_study(folder):
    """load a finished synthetic study and check it against its saved cases and sources."""

    folder = Path(folder).resolve()
    data = json.loads((folder/"study.json").read_text())
    if data["kind"] != "synthetic" or data["status"] not in ("PASS", "COMPLETE_WITH_UNVERIFIED"):
        raise ValueError("Reporting requires a finished, explicitly synthetic study")
    check_sources(data)
    for name, expected in data["record_sha256"].items():
        if digest(folder/name) != expected:
            raise ValueError(f"Recorded case changed: {name}")
    for group in ("cases", "refinements"):
        for row in data[group]:
            name = f"{row['recipe']}--{row['scenario']['name']}"
            if saved_case(folder/group/name) != row:
                raise ValueError(f"Study summary differs from its saved case: {name}")
    return data


# figures

def _passed_reference(cases, recipe):
    """the passing reference-scenario case for a recipe, or None."""

    for case in cases:
        if case["recipe"] == recipe and case["scenario"]["name"] == "reference" and case["status"] == "PASS":
            return case
    return None


def _plot_process_window(plt, data, output):
    """grid of feasibility states over pulse and purge ratios, for reference and all scenarios."""

    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    recipes = data["summary"]["recipes"]
    plan = data["plan"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    for axis, key, title in zip(axes, ("nominal", "all_scenarios"), ("Reference scenario", "Every declared scenario")):
        matrix = np.zeros((len(plan["purge_ratios"]), len(plan["a_pulse_ratios"])))
        for row in recipes:
            x = plan["a_pulse_ratios"].index(row["pulse_ratio"])
            y = plan["purge_ratios"].index(row["purge_ratio"])
            matrix[y, x] = STATES.index(row[key])
            axis.text(x, y, CELL_TEXT[row[key]], ha="center", va="center", fontsize=10)

        # one color per state index 0..4, centred on the integers

        axis.imshow(matrix, cmap=ListedColormap(COLORS), vmin=-.5, vmax=4.5, origin="lower", aspect="auto")
        axis.set(xticks=range(len(plan["a_pulse_ratios"])), xticklabels=plan["a_pulse_ratios"],
                 yticks=range(len(plan["purge_ratios"])), yticklabels=plan["purge_ratios"],
                 xlabel="A pulse / residence time", ylabel="Each purge / residence time", title=title)
    fig.suptitle(f"Synthetic 1D process window · only the {len(recipes)} declared recipes")
    handles = [Patch(color=color, label=label) for color, label in zip(COLORS, LABELS)]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .95))
    fig.savefig(output/"process-window.png", dpi=FIGURE_DPI)
    plt.close(fig)


def _plot_scenario_ranges(plt, data, output):
    """mean gpc range over scenarios for each recipe, with the reference value marked."""

    recipes = data["summary"]["recipes"]
    fig, axis = plt.subplots(figsize=(10, 4.5))
    for index, row in enumerate(recipes):
        bounds = row["envelope"]["ranges"].get("mean_gpc_angstrom")
        reference = _passed_reference(data["cases"], row["recipe"])
        if bounds is not None:
            axis.vlines(index, *bounds, color=RANGE_COLOR, linewidth=4)
            axis.scatter([index, index], bounds, marker="_", color=RANGE_COLOR, s=90)
        else:
            axis.text(index, .03, "Unverified", rotation=90, ha="center", transform=axis.get_xaxis_transform(), fontsize=9)
        if reference is not None:
            axis.scatter(index, reference["models"]["spatial"]["metrics"]["mean_gpc_angstrom"], color=REFERENCE_COLOR, zorder=3)

    # empty artists give the legend its two entries

    axis.plot([], [], color=RANGE_COLOR, linewidth=4, label="Finite scenario range")
    axis.scatter([], [], color=REFERENCE_COLOR, label="Reference scenario")
    tick_labels = [f"{r['pulse_ratio']:g} / {r['purge_ratio']:g}" for r in recipes]
    axis.set(xticks=range(len(recipes)), xticklabels=tick_labels,
             xlabel="A pulse / each purge (both in residence times)", ylabel="Mean equivalent GPC (Å/cycle)",
             title="Synthetic scenario spread · these are not confidence intervals")
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output/"scenario-ranges.png", dpi=FIGURE_DPI)
    plt.close(fig)


def _plot_recipe_candidates(plt, data, output):
    """cycle time against precursor use for each recipe, with the selected one ringed."""

    recipes = data["summary"]["recipes"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for axis, key in zip(axes, ("nominal", "all_scenarios")):
        selection = data["selections"][key]
        for state, color, label in zip(STATES, COLORS, LABELS):
            rows = [row for row in recipes if row[key] == state]
            if rows:
                times = [r["objectives"]["cycle_time_s"]*MS_PER_S for r in rows]
                moles = [r["objectives"]["precursor_moles"]*NMOL_PER_MOL for r in rows]
                axis.scatter(times, moles, color=color, edgecolor=EDGE_COLOR, s=65, label=label)
        for row in recipes:
            x = row["objectives"]["cycle_time_s"]*MS_PER_S
            y = row["objectives"]["precursor_moles"]*NMOL_PER_MOL
            axis.annotate(f"{row['pulse_ratio']:g}/{row['purge_ratio']:g}", (x, y), xytext=(4, 5),
                          textcoords="offset points", fontsize=9)
            if row["recipe"] == selection["selected"]:
                axis.scatter(x, y, facecolor="none", edgecolor=SELECTED_COLOR, s=180, linewidth=2)
        if key == "nominal":
            title = "Reference"
        else:
            title = "Every declared scenario"
        axis.set(xlabel="Cycle time (ms)", ylabel="Precursor delivered (nmol)", title=title)
        axis.margins(.15)
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Finite recipe comparison · labels are A/purge ratios; a ring marks a verified selection")

    # one shared legend without repeated labels

    legend = {}
    for axis in axes:
        handles, labels = axis.get_legend_handles_labels()
        legend.update(zip(labels, handles))
    fig.legend(legend.values(), legend.keys(), loc="lower center", ncol=3, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, .96))
    fig.savefig(output/"recipe-candidates.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_results(data, output):
    """write the process window, scenario range and recipe candidate figures."""

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _plot_process_window(plt, data, output)
    _plot_scenario_ranges(plt, data, output)
    _plot_recipe_candidates(plt, data, output)


# data for the local results view

def _reduced_profile(profile):
    """about 100 evenly spaced points plus the lowest and highest A completion."""

    # only the drawn curve is reduced. every reported metric uses all cells.

    last = len(profile["z_m"])-1
    evenly = np.linspace(0, last, PROFILE_POINTS).astype(int)
    lowest = np.argmin(profile["a_completion"])
    highest = np.argmax(profile["a_completion"])
    indices = np.unique(np.r_[evenly, lowest, highest])
    reduced = {}
    for key, values in profile.items():
        reduced[key] = [values[i] for i in indices]
    return reduced


def viewer_data(data):
    """per-case rows and study summary for the results page."""

    rows = []
    for row in data["cases"]:
        item = {}
        for key in ("recipe", "scenario", "status", "pulse_ratio", "purge_ratio", "residence_s"):
            item[key] = row[key]
        item["state"] = feasibility([row], 1)
        item["reason"] = row.get("reason")
        item["models"] = row.get("models")
        item["cells"] = row.get("accepted_cells")
        item["profile"] = None
        if "profile" in row:
            item["profile"] = _reduced_profile(row["profile"])
        rows.append(item)
    return dict(kind="synthetic", status=data["status"], cases=rows, plan=data["plan"],
                channel_length_m=data["base"]["channel"]["length"],
                summary=data["summary"], selections=data["selections"],
                verified_pairs=sum(row["status"] == "PASS" for row in data["cases"]))


# the written report

def _uncertainty_accounting():
    """one row per uncertainty source and what is (and is not) known about it."""

    return [
        dict(source="Numerical resolution", status="Measured grid and time changes", probability_model=None,
             note="Resolution-change indicators are kept separate; they are not rigorous error bounds."),
        dict(source="Gamma, kA, kB", status="Illustrative finite scenarios only", probability_model=None,
             note="No fitted covariance or physical parameter distribution is available."),
        dict(source="DEZ transport", status="Physical value and uncertainty pending", probability_model=None,
             note="D_A factors modify a labelled synthetic input only; diffusivity is never fitted."),
        dict(source="Density and observation mapping", status="Fixed conditional mapping", probability_model=None,
             note="5400 kg/m³ at 150 C; no density uncertainty has been assigned."),
        dict(source="Measurement/calibration and digitization", status="Unreported in this synthetic study", probability_model=None,
             note="No experimental observations or invented error bars enter these calculations."),
        dict(source="Model discrepancy", status="Unquantified", probability_model=None,
             note="A 0D/1D comparison does not establish error against the physical reactor.")]


def _report_lines(data, view, accounting):
    """markdown lines for report.md."""

    lines = ["# Synthetic scenario and recipe study", "",
             f"**{view['verified_pairs']}/{len(data['cases'])} pairs verified. Study status: {data['status']}.**", "",
             "These are finite mathematical examples. Physical DEZ transport, its uncertainty and experimental validation remain pending.", "",
             "## Uncertainty accounting", "", "| Source | Status | Meaning |", "|---|---|---|"]
    for r in accounting:
        lines.append(f"| {r['source']} | {r['status']} | {r['note']} |")
    lines += ["", "Every declared scenario was enumerated. The set has no sampling probability and does not cover a continuous parameter box.", "",
              "![Scenario ranges](scenario-ranges.png)", "", "## Discrete process window", "",
              "![Process window](process-window.png)", "",
              "Feasibility requires A completion ≥0.9, B remaining ≤0.1, both scaled purge residuals ≤0.01, numerical verification and the conditional wall screen. Uniformity is reported without inventing another constraint.", "",
              "## Finite optimization", "", "![Candidate comparison](recipe-candidates.png)", "",
              "| Selection | Result | Recipe |", "|---|---|---|"]
    for name, row in data["selections"].items():
        lines.append(f"| {name} | {row['status']} | {row['selected'] or 'None'} |")
    lines += ["", "Objectives are prescribed cycle time and total precursor delivery. Each selected Pareto recipe was rechecked on a doubled spatial grid and with tighter time integration. No continuous/global optimum or physical recipe recommendation is claimed.", "",
              "## Exceptions", "", "| Trial | Status | Reason |", "|---|---|---|"]
    for row in data["cases"] + data["refinements"]:
        if row["status"] != "PASS":
            lines.append(f"| {row['recipe']} / {row['scenario']['name']} | {row['status']} | {row.get('reason', '')} |")
    lines += ["", "The local results view reads these same saved records. Full-resolution metrics are retained even where the displayed curve uses fewer points. Raw cycles, accounting and solver settings remain in the study folder.", "",
              "Phase 10 is deferred: no extra physics, virtual sensors, fault model or experimental-design assumptions were needed for this block.", ""]
    return lines


def build_report(folder, output):
    """write figures, the results page, summary.json, report.md and provenance.json."""

    folder = Path(folder).resolve()
    output = Path(output).resolve()
    data = read_study(folder)
    output.mkdir(parents=True, exist_ok=True)
    plot_results(data, output)

    # the results page gets the data inlined, with "<" escaped so it cannot close the script tag

    view = viewer_data(data)
    template = Path(__file__).with_name("process_view.html")
    payload = json.dumps(view, allow_nan=False).replace("<", "\\u003c")
    (output/"index.html").write_text(template.read_text().replace("__STUDY_DATA__", payload))

    # summary.json and report.md

    accounting = _uncertainty_accounting()
    summary = data["summary"] | dict(status=data["status"], verified_pairs=view["verified_pairs"],
                                     total_pairs=len(data["cases"]), uncertainty_accounting=accounting)
    summary["selections"] = data["selections"]
    write_json(output/"summary.json", summary)
    (output/"report.md").write_text("\n".join(_report_lines(data, view, accounting)))

    # hashes of the inputs and of every output written above

    input_hashes = {}
    for path in [folder/"study.json", Path(__file__), template]:
        input_hashes[str(path)] = digest(path)
    output_hashes = {}
    for path in output.iterdir():
        if path.is_file() and path.name != "provenance.json":
            output_hashes[path.name] = digest(path)
    write_json(output/"provenance.json", dict(kind="synthetic", input_sha256=input_hashes,
                                              output_sha256=output_hashes))
    print(output/"index.html")
