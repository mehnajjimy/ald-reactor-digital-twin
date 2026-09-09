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
| 1–13 | Describe the scope, import the plotting/file tools, select a noninteractive renderer, and locate the saved data and colors. |
| 16–22 | Set fonts, colors, axes and grid lines; these are display settings only. |
| 25–29 | Add the title and scope label, save a PNG and close the figure. |
| 32–41 | Create three aligned cycle panels and draw the saved 3/5/3/5 inlet schedule. |
| 42–46 | Draw the saved spatial termination range and area mean with a 0–1 scale. |
| 47–49 | Draw the already extracted conditional mass trace and label its units. |
| 50–56 | Mark recipe switches, align time axes and save the cycle figure. |
| 59–74 | Draw completion and turnover profiles beside their matched 0D values; label axes and the legend. |
| 75–76 | Save the comparison with its synthetic scope and endpoint values. |
| 79–87 | Create two heatmaps from the saved display arrays, with one shared 0–1 color scale. |
| 88–93 | Mark switches, add color bars and position units, and save the heatmaps. |
| 96–105 | Verify the data hash, apply the style, open the arrays and render all three figures. |
| 108–109 | Call the renderer only when this file is run as a script. |
