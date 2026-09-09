# GUI code, line by line

These tables explain every nonblank line of the reviewed local server and its
interface. Related lines share a row. Braces and closing tags end the operation
described in their row. This keeps explanations outside the working code.
Line numbers must follow later source edits.

The server dispatches the shared solver and reads saved output. JavaScript
changes presentation, never equations or acceptance thresholds. DEZ remains a
synthetic placeholder; physical fitting stays blocked.

## `src/ald_twin/gui.py`

| Lines | What they do and why |
|---|---|
| 1–16 | Describe the local worker boundary and import UTC time, the standard HTTP server, JSON, media types, environment/filesystem tools, name matching, secure random tokens, signals, subprocesses, platform information, locking, URL parsing and browser launch. |
| 18–22 | Reuse input inspection/preparation, packaged examples, atomic JSON writing, comparison and verified saved-result reading. Locate interface assets beside this module. |
| 25–29 | Read a JSON file and require an object. Reject other JSON types with a clear filename-specific error before callers use object fields. |
| 32–36 | Construct the worker's argument list. A source installation uses the Python CLI; a frozen bundle uses its own `--worker` dispatcher. Both receive the same `simulate` command, input path and new output folder. |
| 39–48 | Define one workspace, resolve/create its run collection, and initialize its lock, worker reference, active-job record and closed flag. |
| 50–56 | Accept only a short plain run name, resolve it beneath the collection and reject any path or symlink escaping that collection. Return the checked path. |
| 58–71 | Inspect direct child directories, skipping hidden/non-directory entries. Read usable run metadata, note whether a manifest exists, skip malformed entries, and return newest first. The list is an index; opening a completed result verifies its files. |
| 73–78 | Resolve a selected run and verify its manifest when present. Otherwise read its partial record. Reject saved records that claim unsupported scientific status. |
| 79–83 | For a partial run, clear acceptance, feasibility and accepted-grid claims in the response. Keep running/interrupted/error states; downgrade other statuses to unverified. Return that record with its saved inputs without rewriting the original. |
| 85–89 | Refresh an active job only after its worker exits. Locate the active run once exit is known. |
| 90–97 | Verify a completed manifest before marking output ready. If verification fails, return an error record with the reason and leave readiness false. |
| 98–105 | Read unfinished progress, or use an empty object if none was written. Preserve unreadable/malformed progress as `run-damaged.json` before constructing the exit record. |
| 106–112 | Distinguish a requested stop from a worker error. Retain synthetic/blocked status and process identity, clear numerical acceptance, mark recipe feasibility unverified, and explain why execution ended. |
| 113–117 | Create the partial output folder if needed, restore input provenance only when inputs are missing, save the exit record atomically, and update the active job to stopped and not ready. |
| 119–124 | Lock status inspection, refresh any exited worker and return either no active job or the small set of live job flags used by the page. |
| 125–133 | For a running job, include its submitted inputs and read its current progress. Missing progress means startup; unreadable progress produces a visible status message while preserving the ability to stop. For an exited job use the refreshed record. |
| 134–138 | Return only status, stage, reason and decision fields. While stopping, replace the stage text with the retained-attempt message. |
| 140–147 | Validate submitted inputs before dispatch. Under the lock, reject closed workspaces and a second active job, after refreshing any finished worker. |
| 148–153 | Create a UTC/random run identifier, ensure the hidden control folder exists, save the validated worker input, and set numerical libraries to one thread in the child environment. |
| 154–158 | Open a retained worker log and launch the shared command with stdout/stderr redirected there. Record the active inputs and flags, then return the current status. |
| 160–172 | Lock stop handling and refresh first. Mark a live job stopped by request, send termination on Windows or interrupt elsewhere, tolerate an already-exited process, then return status. |
| 174–185 | Mark the workspace closed before requesting stop so late start requests are rejected. Wait up to ten seconds, kill a worker that remains, wait for exit, and refresh its retained record under the lock. |
| 188–190 | Define the request handler and suppress routine HTTP access-log noise. |
| 192–202 | Encode JSON without nonfinite values, or send supplied bytes for assets. Set status, media type and length; prohibit caching and type sniffing; constrain page resources to the local origin and deny framing; then write the response body. |
| 204–212 | Allow only this server's loopback host/port and matching optional origin. API calls must also supply its random launch token, compared without a content-dependent early exit. |
| 214–223 | Parse GET paths, enforce local access, capture the workspace, and serve the HTML after inserting the launch token and desktop-mode flag. |
| 224–233 | Route reads for packaged process inspection, saved-run index, live state, desktop sound and a selected saved result. No route here calculates a new run. |
| 234–237 | For report export, validate the selected run's saved manifest before returning the report bytes as UTF-8 Markdown text. |
| 238–244 | Serve only the listed CSS, JavaScript and three sound assets, selecting their media type. Return not-found for other paths and readable bad-request responses for file/data errors. |
| 246–255 | Enforce the API token before POST processing. Require JSON and a body between one byte and 512 KB, then decode it. |
| 256–265 | Capture the path, workspace and optional native operations; route native sound/export requests and read-only input inspection. |
| 266–269 | Dispatch a validated new job with HTTP accepted status, or request the active job's stop. |
| 270–278 | Require one to four string run names for comparison, resolve each within the collection, and read verified saved data. Return not-found for unknown routes, conflict for lifecycle errors, and bad-request for malformed data/files. |
| 281–291 | Validate the port, bind the standard threaded server only to loopback, and create its launch token and workspace. If workspace setup fails, close the socket before propagating the error. |
| 294–298 | Create the browser service and print its actual local address and run collection. |
| 299–309 | Optionally open the browser, serve requests until interrupted, and always close the workspace and socket, including browser-launch or shutdown errors. |

## `src/ald_twin/ui/workspace.js`

| Lines | What they do and why |
|---|---|
| 1–7 | State the presentation boundary, define element lookup, read the launch token/desktop flag, collect the four recipe fields and map saved recipe decisions to readable labels. |
| 8–13 | Initialize process/run lists, draft/inspection/displayed records, activity flags, request counters, pending timers and sound state. Restore browser sound preference when storage is available. |
| 15–22 | Send token-protected GET or JSON POST requests, decode the JSON response, throw a useful error on failure and return successful data. |
| 24–32 | Clear the error panel, hide it for an empty list, and append each error as text in a list item. Text insertion prevents file/input content from becoming page markup. |
| 34–42 | Play only when sounds are enabled. Stop the previous cue, load the selected local WAV, use quiet fixed volumes and report playback failure without touching calculation state. |
| 44–47 | Update the single sound button's wording and accessible pressed state. |
| 49–60 | Disable Run while busy, validating, disconnected or invalid; update its label and Stop visibility. Lock input/process/result selection while starting/running, show activity, and allow report saving only for ready output. |
| 62–64 | Format ordinary values, fractions as percentages, and purge seconds as milliseconds. Keep unavailable values and uncleared purges distinct; zero remains a real number. |
| 66–75 | Replace a table body, then append one row per supplied record and one text cell per value. The nested loops follow the table's rows and columns. |
| 77–88 | Define the six existing output quantities and their display conversion, then produce two value columns with explicit unavailable entries when a model is missing. |
| 90–96 | Recursively preserve array order and sort object keys for comparison; pass primitive values through. Key order alone must not make saved and draft inputs appear different. |
| 98–100 | Show the draft warning only when a displayed result exists and its saved inputs differ from current inputs. |
| 102–118 | Read available channel, chemistry and diffusion objects. Build the explicit input/value/unit rows, including reference conditions, capacity, rates, grids and optional film density, then render them. |
| 119–128 | Rebuild the compact reactor summary, converting length/gap to millimeters and temperature to Celsius while retaining pressure in pascals. Create label/value pairs with text nodes. |
| 129–135 | Show the process name, then display each provenance source and validity statement as text. |
| 136–143 | Display residence time and total cycle time from Python's inspection result. Sum only the returned segment durations; size the four sequence bars from draft duration ratios and refresh the draft warning. |
| 145–157 | Number each validation request and mark inspection pending. Apply only the latest response/error; an older request cannot replace a newer validation decision or re-enable controls prematurely. |
| 159–166 | Clone selected/imported inputs, populate the four recipe fields, update the selected process button, and request Python validation. |
| 168–181 | Draw only a visible saved profile. Set plot dimensions, include any mixed reference in the vertical range, add readable padding, and map saved position/turnover to SVG coordinates using the saved channel length. Clear the previous plot. |
| 182–187 | Define a small SVG helper that creates a namespaced element, applies its attributes, adds optional text and appends it to the chart. |
| 188–204 | Label turnover; draw four horizontal guides and a width-dependent number of position ticks. Add the millimeter axis label, optional dashed mixed reference and blue spatial path using the saved samples. |
| 206–218 | Read only the displayed saved record. Show available model output or the empty-state message; label the run origin, numerical decision, recipe decision and verified-grid status independently. |
| 219–233 | Show an available profile, six metrics, film status, failure reason and retained attempt rows. Fill optional spread/purge diagnostics, then refresh the draft warning, controls and chart. |
| 235–244 | Number a saved-result selection, fetch its verified response and ignore stale selections. Adopt its saved inputs only when requested; check again after validation before updating the selected run and display. |
| 246–249 | Build a saved-run label from process ID, local time (or run ID) and its retained status. |
| 251–256 | Replace a dropdown's options while preserving its prior choice if that run remains present. |
| 258–267 | Refresh the run index and saved-run picker. Use manifest-bearing runs for comparison choices, update the comparison prompt, and retain the displayed run's selection. Opening/comparing still verifies the files. |
| 269–289 | Capture the two comparison choices, hide stale output, fetch the saved comparison and ignore a response for changed choices. Render process, ordered recipe, independent decisions and spatial metrics; display errors only for the still-current pair. |
| 291–297 | Select one Results/Inputs/Compare view, update tab pressed states, hide other views and redraw the plot if visible. |
| 299–308 | In desktop mode request a native export and report errors. In a browser create a temporary download URL and link, trigger its download, then release the URL after one second. |
| 310–320 | Capture the job counter, request live state, ignore an older job response, restore connected status and update activity/stage/Stop controls. Remember the current running job ID. |
| 321–336 | Handle each observed completion once. Refresh saved runs, ignore completion continuation if the user changed selection or started another job, then open the finished output. Play completion only for ready artifacts of the same job. Report errors or disconnection, then schedule the next poll one second later. |
| 338–350 | Restore native sound preference when applicable, label the toggle, fetch packaged processes and construct plain process buttons with explicit synthetic/DEZ-placeholder subtitles. |
| 351–361 | On process selection, invalidate old result requests, clear the displayed selection, validate the selected process and show its latest saved result without replacing the new draft. Ignore continuation after a newer selection. |
| 362–372 | Load saved runs and live state. Restore active-job inputs when running; otherwise choose the packaged ZnO example or first available process. Open matching saved output if available, retain error visibility, and begin polling. |
| 374–387 | Remember the prior sound choice and disable the toggle while saving so requests cannot arrive out of order. Update its label, save the native preference when applicable, then the browser preference. Restore the prior choice and show an error if saving fails; always re-enable the toggle. Play the click or stop current audio according to the final choice. |
| 388–390 | Wire the three view buttons to view selection and the optional click cue. |
| 391–396 | Repair a missing/malformed recipe object, store the edited duration as a number or null, invalidate prior inspection and disable Run. Wait 180 ms after the latest edit before validating, avoiding a request for every keystroke. |
| 397–403 | Wire saved-result selection and its errors, both comparison dropdowns and the Open inputs button's file chooser. |
| 404–414 | Read one selected JSON file up to 512 KB, require an object, invalidate older selections, clear prior output and validate/show its inputs. Report parsing/data errors and clear the file control so the same file can be reopened. |
| 415–417 | Export a formatted copy of the current inputs, including recipe edits. |
| 418–425 | Capture the displayed run ID, fetch its verified report with the launch token, export that report under the captured run name and display any error. Changing selection while downloading cannot relabel the report. |
| 426–435 | Invalidate old job/selection responses, lock controls during startup and clear old errors. Start the shared worker; retain its ID, select Results and show/play startup feedback. Always finish the startup state and invalidate earlier polls. |
| 436–440 | Disable Stop during its request, show the retained-attempt message on success and restore the control if the request fails. |
| 441–442 | Redraw when the chart changes size, then initialize the workspace with a visible startup error if loading fails. |

## `src/ald_twin/ui/index.html`

| Lines | What they do and why |
|---|---|
| 1–11 | Define an English HTML page with UTF-8 and responsive viewport, placeholders for its launch token/desktop mode, its title, shared stylesheet and deferred JavaScript. |
| 12–18 | Open the page/workspace and its header, showing the ALD name, flexible spacing and one initially-off accessible sound toggle. |
| 19–24 | Define Open inputs and its hidden JSON chooser, the process label, disabled report/run controls and initially hidden Stop. JavaScript enables controls only when their prerequisites hold. |
| 25–32 | Define the project sidebar with process buttons, a labeled saved-result picker, compact reactor values. The repeated lower-left limits block is removed. |
| 33–38 | Open the main workspace and its three accessible view buttons, initially selecting Results. |
| 39–46 | Start Results with its saved-origin label and initially hidden model data. Provide verified-grid text, the spatial/mixed legend and an accessible SVG plot. |
| 47–54 | Provide the two-model metric table, film explanation, empty-state/failure text and collapsed numerical diagnostics/attempt table, then close Results. |
| 55–59 | Define the initially hidden Inputs view, Save inputs button, input/value/unit table and collapsed sources/model-scope disclosure. |
| 60–66 | Define the initially hidden comparison view with two labeled choices, an empty-state prompt and table; close the main workspace. |
| 67–69 | Open the Recipe inspector and its input container. |
| 70–73 | Define A pulse, A purge, B pulse and B purge numeric fields with explicit accessible residence-time labels, nonnegative input bounds and unrestricted decimal steps. Python still performs the authoritative validation. |
| 74–76 | Add four decorative duration bars, their sequence labels and the calculated recipe-time text; close the recipe inputs. |
| 77–79 | Show separate displayed-result numerical and recipe decisions plus the fixed blocked physical-fit status; close the inspector and body layout. |
| 80–83 | Provide the initially hidden draft warning, accessible validation alerts, indeterminate activity bar and live status footer. The repeated model-scope tagline is removed. |
| 84–86 | Close the workspace container, body and document. |

## `src/ald_twin/ui/workspace.css`

| Lines | What they do and why |
|---|---|
| 1–2 | Use a light page background and remove the browser's default body margin. |
| 4 | Define the approved blue/gray palette, spacing, forced light controls, system font, ink, white workspace and border. |
| 5–7 | Include borders/padding in sizes, make hidden elements reliably disappear, and give controls the shared font/color with nearly square corners. |
| 8–11 | Style buttons, hover and disabled states; give inputs/selects white backgrounds, plain borders and compact padding. |
| 12–13 | Set checkbox/range appearance. These retained selectors do not add controls to the page. |
| 14–18 | Lay out the light header, compact blue ALD mark, app name, optional preview text and flexible spacer. The preview selector has no active element. |
| 19–21 | Arrange the wrapping toolbar, subdued process text and pale-blue primary action. |
| 22–25 | Lay out sidebar, flexible center and inspector columns; style the sidebar, uppercase panel title and group labels. |
| 26–28 | Make process choices full-width, square and left-aligned; mark selection with blue fill/border and keep subtitles subdued. |
| 29–32 | Pad property panels, arrange label/value pairs in two columns, mute labels and align numeric glyph widths. |
| 33 | Style small supporting notes. |
| 34–38 | Keep the center white, arrange tabs, mark the active tab with a blue underline and pad each view. |
| 39–41 | Align wrapping heading rows and define compact heading/metadata text. |
| 42–47 | Arrange the plot legend and solid/dashed swatches; size the SVG to its panel and style its labels. |
| 48–52 | Allow horizontal table scrolling, collapse borders, style headers/cells, align numbers right and labels left, and let label text wrap. |
| 53–54 | Use amber for review/unverified decisions and green for passed decisions. The saved record chooses the class. |
| 55–58 | Give the inspector a pale panel/divider and align each recipe label, numeric field and unit. |
| 59–61 | Draw the four duration segments with small gaps; pulse segments are blue and purge segments gray. JavaScript replaces initial proportions with draft values. |
| 62–64 | Divide and space the separate result decisions, with modest emphasis on their values. |
| 65–69 | Style the wrapping status footer, thin activity track, its moving element, amber draft warning and red error text. The later activity rule replaces the initial zero width. |
| 70–72 | Permit input-table text to wrap and style compact instructional/empty-state text. |
| 73 | Below 870 pixels, reduce the sidebar and place the recipe inspector across the bottom in three sections, adjusting dividers. |
| 74 | Below 540 pixels, stack the workspace, compact the header/tables/tabs, put process buttons side by side, hide less-used sidebar groups and enlarge recipe fields. The later rule restores the saved-run picker. |
| 75–76 | Enlarge touch controls and input text for coarse pointers. Disable transitions when reduced motion is requested. |
| 77–79 | Fill the viewport, reserve body height beneath surrounding controls and size the saved-run dropdown within the sidebar. |
| 80–83 | Arrange the two comparison selectors with equal widths and make long saved-origin labels wrap. |
| 84–89 | Style validation alerts and their lists, compact disclosure sections, clickable summaries and wrapping source text. |
| 90–92 | Replace the initial activity width with a moving 30% segment, highlight the enabled sound toggle and define the movement. It indicates activity, not a percentage complete. |
| 93–98 | On narrow screens remove the large body minimum, restore the saved-run picker below process buttons and stack comparison choices at full width. |
| 99 | For reduced motion, stop activity animation and show a static full-width activity strip. |
