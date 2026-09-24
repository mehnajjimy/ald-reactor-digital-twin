# README figures

The three plots read the saved synthetic ZnO-equivalent example at 150 °C.
No new simulation or campaign is needed to render them:

```sh
.venv/bin/python -m pip install 'matplotlib>=3.9'
.venv/bin/python scripts/render_readme_figures.py
```

The compact arrays are in `docs/media/synthetic-cycle.npz`. Their SHA-256 and
the original input, result and manifest hashes are in `docs/media/provenance.json`.
The source run passed the unchanged spatial and time checks at 640 cells.
The full research run stays in the research checkout; these display arrays do
not replace it or independently establish convergence.

The cycle plot shows normalized A/B inlet delivery, the area-weighted mean and
range of A termination, and a conditional retained-mass trace. The latter uses
the existing nu=1 event masses in `ald_twin.cycles`, including ethane leaving the
surface. It can fall during B exposure. It is not an experimental QCM prediction.

The comparison uses the matched 0D and accepted spatial cycle. A completion is
read at the end of the A pulse; turnover counts B events over the entire cycle.
Turnover can slightly exceed one because residual A and incoming B overlap.
The heatmaps average each four adjacent cells for display and retain every saved
time sample. Gas color represents mole fraction divided by the inlet fraction.
The blue surface band represents termination, not film thickness.

The desktop image is an unedited screenshot of the actual 0.1.2 Mac build opening
a saved synthetic run with the same input and output values. It is not a mockup.

## Plot code

`scripts/render_readme_figures.py` contains presentation code only:

| Lines | What they do |
|---|---|
| 1–13 | Describe the scope, import the plotting/file tools, select a noninteractive renderer, and locate the saved data. |
| 15–21 | Name the display colors. |
| 23–28 | Name the saved 3/5/3/5 cycle timing in residence times and the three phase boundaries. |
| 31–38 | Set fonts, colors, axes and grid lines; these are display settings only. |
| 41–46 | Add the title and scope label, save a PNG and close the figure. |
| 49–64 | Create three aligned cycle panels and draw the saved 3/5/3/5 inlet schedule. |
| 66–71 | Draw the saved spatial termination range and area mean with a 0–1 scale. |
| 73–76 | Draw the already extracted conditional mass trace and label its units. |
| 77–83 | Mark recipe switches, align time axes and save the cycle figure. |
| 86–106 | Draw completion and turnover profiles beside their matched 0D values; label axes and the legend. |
| 107–108 | Save the comparison with its synthetic scope and endpoint values. |
| 111–119 | Create two heatmaps from the saved display arrays, with one shared 0–1 color scale. |
| 120–127 | Mark switches, add color bars and position units, and save the heatmaps. |
| 130–142 | Verify the data hash, apply the style, open the arrays and render all three figures. |
| 145–146 | Call the renderer only when this file is run as a script. |
