"""Scientific figures and a local read-only view of verified study records."""

import json
from pathlib import Path

import numpy as np

from .process_runner import ROOT, check_sources, digest, saved_case
from .process_study import feasibility, write_json

STATES = ["fail", "pass", "unresolved", "unverified", "outside-screen"]
COLORS = ["#edc4ba", "#9bd2bd", "#efdb9e", "#e6ebf0", "#cdbede"]
LABELS = ["Fails constraints", "Passes constraints", "Near threshold", "Not verified", "Outside wall screen"]


def read_study(folder):
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


def plot_results(data, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    recipes, plan = data["summary"]["recipes"], data["plan"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    for axis, key, title in zip(axes, ("nominal", "all_scenarios"), ("Reference scenario", "Every declared scenario")):
        matrix = np.zeros((len(plan["purge_ratios"]), len(plan["a_pulse_ratios"])))
        for row in recipes:
            x, y = plan["a_pulse_ratios"].index(row["pulse_ratio"]), plan["purge_ratios"].index(row["purge_ratio"])
            matrix[y, x] = STATES.index(row[key])
            axis.text(x, y, {"pass": "Pass", "fail": "Fail", "unresolved": "Near limit",
                            "unverified": "Unverified", "outside-screen": "Outside screen"}[row[key]],
                      ha="center", va="center", fontsize=10)
        axis.imshow(matrix, cmap=ListedColormap(COLORS), vmin=-.5, vmax=4.5, origin="lower", aspect="auto")
        axis.set(xticks=range(len(plan["a_pulse_ratios"])), xticklabels=plan["a_pulse_ratios"],
                 yticks=range(len(plan["purge_ratios"])), yticklabels=plan["purge_ratios"],
                 xlabel="A pulse / residence time", ylabel="Each purge / residence time", title=title)
    fig.suptitle(f"Synthetic 1D process window · only the {len(recipes)} declared recipes")
    fig.legend(handles=[Patch(color=c, label=l) for c, l in zip(COLORS, LABELS)],
               loc="lower center", ncol=3, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .95))
    fig.savefig(output/"process-window.png", dpi=170)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 4.5))
    for index, row in enumerate(recipes):
        bounds = row["envelope"]["ranges"].get("mean_gpc_angstrom")
        reference = next((case for case in data["cases"] if case["recipe"] == row["recipe"]
                          and case["scenario"]["name"] == "reference" and case["status"] == "PASS"), None)
        if bounds is not None:
            axis.vlines(index, *bounds, color="#1c6c91", linewidth=4)
            axis.scatter([index, index], bounds, marker="_", color="#1c6c91", s=90)
        else:
            axis.text(index, .03, "Unverified", rotation=90, ha="center", transform=axis.get_xaxis_transform(), fontsize=9)
        if reference is not None:
            axis.scatter(index, reference["models"]["spatial"]["metrics"]["mean_gpc_angstrom"], color="#be533b", zorder=3)
    axis.plot([], [], color="#1c6c91", linewidth=4, label="Finite scenario range")
    axis.scatter([], [], color="#be533b", label="Reference scenario")
    axis.set(xticks=range(len(recipes)), xticklabels=[f"{r['pulse_ratio']:g} / {r['purge_ratio']:g}" for r in recipes],
             xlabel="A pulse / each purge (both in residence times)", ylabel="Mean equivalent GPC (Å/cycle)",
             title="Synthetic scenario spread · these are not confidence intervals")
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output/"scenario-ranges.png", dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for axis, key in zip(axes, ("nominal", "all_scenarios")):
        selection = data["selections"][key]
        for state, color, label in zip(STATES, COLORS, LABELS):
            rows = [row for row in recipes if row[key] == state]
            if rows:
                axis.scatter([r["objectives"]["cycle_time_s"]*1000 for r in rows],
                             [r["objectives"]["precursor_moles"]*1e9 for r in rows],
                             color=color, edgecolor="#283c50", s=65, label=label)
        for row in recipes:
            x, y = row["objectives"]["cycle_time_s"]*1000, row["objectives"]["precursor_moles"]*1e9
            axis.annotate(f"{row['pulse_ratio']:g}/{row['purge_ratio']:g}", (x, y), xytext=(4, 5),
                          textcoords="offset points", fontsize=9)
            if row["recipe"] == selection["selected"]:
                axis.scatter(x, y, facecolor="none", edgecolor="#116d50", s=180, linewidth=2)
        axis.set(xlabel="Cycle time (ms)", ylabel="Precursor delivered (nmol)",
                 title="Reference" if key == "nominal" else "Every declared scenario")
        axis.margins(.15)
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Finite recipe comparison · labels are A/purge ratios; a ring marks a verified selection")
    legend = {}
    for axis in axes:
        handles, labels = axis.get_legend_handles_labels()
        legend.update(zip(labels, handles))
    fig.legend(legend.values(), legend.keys(), loc="lower center", ncol=3, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, .96))
    fig.savefig(output/"recipe-candidates.png", dpi=170)
    plt.close(fig)


def viewer_data(data):
    rows = []
    for row in data["cases"]:
        item = {key: row[key] for key in ("recipe", "scenario", "status", "pulse_ratio", "purge_ratio", "residence_s")}
        item["state"] = feasibility([row], 1)
        item["reason"] = row.get("reason")
        item["models"] = row.get("models")
        item["cells"] = row.get("accepted_cells")
        item["profile"] = None
        if "profile" in row:
            profile = row["profile"]
            # Only the drawn curve is reduced. Every reported metric uses all cells.
            indices = np.unique(np.r_[np.linspace(0, len(profile["z_m"])-1, 100).astype(int),
                                      np.argmin(profile["a_completion"]), np.argmax(profile["a_completion"])])
            item["profile"] = {key: [values[i] for i in indices] for key, values in profile.items()}
        rows.append(item)
    return dict(kind="synthetic", status=data["status"], cases=rows, plan=data["plan"],
                channel_length_m=data["base"]["channel"]["length"],
                summary=data["summary"], selections=data["selections"],
                verified_pairs=sum(row["status"] == "PASS" for row in data["cases"]))


def build_report(folder, output):
    folder, output = Path(folder).resolve(), Path(output).resolve()
    data = read_study(folder)
    output.mkdir(parents=True, exist_ok=True)
    plot_results(data, output)
    view = viewer_data(data)
    template = Path(__file__).with_name("process_view.html")
    payload = json.dumps(view, allow_nan=False).replace("<", "\\u003c")
    (output/"index.html").write_text(template.read_text().replace("__STUDY_DATA__", payload))
    accounting = [
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
    summary = data["summary"] | dict(status=data["status"], verified_pairs=view["verified_pairs"],
                                     total_pairs=len(data["cases"]), uncertainty_accounting=accounting)
    summary["selections"] = data["selections"]
    write_json(output/"summary.json", summary)
    lines = ["# Synthetic scenario and recipe study", "",
             f"**{view['verified_pairs']}/{len(data['cases'])} pairs verified. Study status: {data['status']}.**", "",
             "These are finite mathematical examples. Physical DEZ transport, its uncertainty and experimental validation remain pending.", "",
             "## Uncertainty accounting", "", "| Source | Status | Meaning |", "|---|---|---|"]
    lines += [f"| {r['source']} | {r['status']} | {r['note']} |" for r in accounting]
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
    (output/"report.md").write_text("\n".join(lines))
    paths = [folder/"study.json", Path(__file__), template]
    write_json(output/"provenance.json", dict(kind="synthetic", input_sha256={str(p): digest(p) for p in paths},
                       output_sha256={p.name: digest(p) for p in output.iterdir() if p.is_file() and p.name != "provenance.json"}))
    print(output/"index.html")
