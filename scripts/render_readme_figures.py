"""render saved synthetic results for the readme; never run a simulation."""

from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

MEDIA = Path(__file__).resolve().parents[1] / "docs/media"
BLUE, TEAL, INK = "#1976c9", "#168e96", "#20364b"


def style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.labelcolor": INK, "text.color": INK, "axes.edgecolor": "#c3ccd5",
        "xtick.color": "#526579", "ytick.color": "#526579",
        "figure.facecolor": "white", "axes.facecolor": "white",
        "grid.color": "#e7edf2", "axes.axisbelow": True})


def finish(fig, name, title, subtitle):
    fig.suptitle(title, x=.09, ha="left", fontsize=21, weight="bold", y=.97)
    fig.text(.09, .865, subtitle, fontsize=11, color="#526579")
    fig.savefig(MEDIA / name, dpi=180, facecolor="white")
    plt.close(fig)


def cycle(data):
    fig, axes = plt.subplots(3, 1, figsize=(11, 7.5), sharex=True)
    fig.subplots_adjust(left=.14, right=.96, top=.84, bottom=.1, hspace=.28)
    t = data["time_tau"]
    axes[0].step([0, 3, 3, 16], [1, 1, 0, 0], color=BLUE, label="A inlet", lw=2.5)
    axes[0].step([0, 8, 8, 11, 11, 16], [0, 0, 1, 1, 0, 0], color=TEAL, label="B inlet", lw=2.5)
    axes[0].set_ylabel("Delivery\n(on / off)")
    axes[0].set_ylim(-.1, 1.35)
    axes[0].set_yticks([0, 1])
    axes[0].legend(loc="upper right", ncol=2, frameon=False)
    axes[1].fill_between(t, data["min_theta"], data["max_theta"], color=BLUE, alpha=.14, label="Spatial range")
    axes[1].plot(t, data["mean_theta"], color=BLUE, lw=2.5, label="Area mean")
    axes[1].set_ylabel("A termination\nfraction")
    axes[1].set_ylim(0, 1.15)
    axes[1].legend(loc="upper right", ncol=2, frameon=False, fontsize=10)
    axes[2].plot(t, data["mass_ng_cm2"], color=INK, lw=2.5)
    axes[2].set_ylabel("Conditional mass\nchange (ng/cm²)")
    axes[2].set_xlabel("Time / carrier residence time")
    for ax in axes:
        for boundary in (3, 8, 11):
            ax.axvline(boundary, color="#c3ccd5", ls=":", lw=1)
        ax.set_xlim(0, 16)
        ax.grid(axis="y")
    finish(fig, "ald-cycle.png", "ALD pulse and purge",
        "Synthetic periodic cycle · conditional ν = 1 mass bookkeeping · not a QCM prediction")


def comparison(data):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    fig.subplots_adjust(left=.09, right=.97, top=.76, bottom=.15, wspace=.3)
    z = data["position_mm"]
    axes[0].plot(z, data["a_completion"]*100, color=BLUE, lw=2.5, label="Spatial model")
    axes[0].axhline(float(data["mixed_completion"])*100, color=TEAL, ls="--", lw=2, label="0D model")
    axes[0].set_ylabel("A completion at pulse end (%)")
    axes[0].set_ylim(88, 101)
    axes[0].legend(loc="lower left", frameon=False)
    axes[1].plot(z, data["turnover"], color=BLUE, lw=2.5)
    axes[1].axhline(float(data["mixed_turnover"]), color=TEAL, ls="--", lw=2)
    axes[1].set_ylabel("Surface turnover per cycle")
    for ax in axes:
        ax.set_xlabel("Position along channel (mm)")
        ax.set_xlim(0, 50)
        ax.grid(axis="y")
    finish(fig, "model-comparison.png", "0D vs spatial model",
        "Synthetic matched inputs · A completion: 97.8% in 0D; 91.1% at the channel outlet")


def heatmap(data):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5), sharey=True)
    fig.subplots_adjust(left=.09, right=.96, top=.74, bottom=.16, wspace=.35)
    for ax, field, title in zip(axes, ("gas_a", "theta"), ("A gas fraction / inlet fraction", "A termination fraction")):
        mesh = ax.pcolormesh(data["time_tau"], data["heatmap_position_mm"], data[field],
            cmap="Blues", vmin=0, vmax=1, shading="nearest", rasterized=True)
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel("Time / residence time")
        ax.set_xlim(0, 16)
        for boundary in (3, 8, 11):
            ax.axvline(boundary, color="#778fa4", ls=":", lw=.8)
        fig.colorbar(mesh, ax=ax, fraction=.045, pad=.03, ticks=[0, .5, 1])
    axes[0].set_ylabel("Position along channel (mm)")
    finish(fig, "transport-heatmap.png", "Transport and surface conversion",
        "Synthetic 640-cell cycle · A pulse 0–3; purge 3–8; B pulse 8–11; purge 11–16")


def main():
    record = json.loads((MEDIA / "provenance.json").read_text())
    path = MEDIA / "synthetic-cycle.npz"
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["plot_data_sha256"]:
        raise ValueError("Saved figure data do not match their provenance")
    style()
    with np.load(path) as data:
        cycle(data)
        comparison(data)
        heatmap(data)


if __name__ == "__main__":
    main()
