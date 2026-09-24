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
| 24–41 | Name the allowed run-name pattern, the 512 KB body limit, the one-to-four comparison limit, the ten-second worker exit wait, the served asset list and the local-only content security policy. |
| 44–49 | Read a JSON file and require an object. Reject other JSON types with a clear filename-specific error before callers use object fields. |
| 52–59 | Construct the worker's argument list. A source installation uses the Python CLI; a frozen bundle uses its own `--worker` dispatcher. Both receive the same `simulate` command, input path and new output folder. |
| 62–71 | Accept a comparison request only as a list of one to four strings. |
| 74–84 | Define one workspace, resolve/create its run collection, and initialize its lock, worker reference, active-job record and closed flag. |
| 86–93 | Accept only a short plain run name, resolve it beneath the collection and reject any path or symlink escaping that collection. Return the checked path. |
| 95–109 | Inspect direct child directories, skipping hidden/non-directory entries. Read usable run metadata, note whether a manifest exists, skip malformed entries, and return newest first. The list is an index; opening a completed result verifies its files. |
| 111–120 | Resolve a selected run and verify its manifest when present. Otherwise read its partial record. Reject saved records that claim unsupported scientific status. |
| 121–125 | For a partial run, clear acceptance, feasibility and accepted-grid claims in the response. Keep running/interrupted/error states; downgrade other statuses to unverified. Return that record with its saved inputs without rewriting the original. |
| 127–135 | Refresh an active job only after its worker exits. Locate the active run once exit is known. |
| 137–145 | Verify a completed manifest before marking output ready. If verification fails, return an error record with the reason and leave readiness false. |
| 147–158 | Read unfinished progress, or use an empty object if none was written. Preserve unreadable/malformed progress as `run-damaged.json` before constructing the exit record. |
| 160–173 | Distinguish a requested stop from a worker error. Retain synthetic/blocked status and process identity, clear numerical acceptance, mark recipe feasibility unverified, and explain why execution ended. |
| 174–178 | Create the partial output folder if needed, restore input provenance only when inputs are missing, save the exit record atomically, and update the active job to stopped and not ready. |
| 180–188 | Lock status inspection, refresh any exited worker and return either no active job or the small set of live job flags used by the page. |
| 190–202 | For a running job, include its submitted inputs and read its current progress. Missing progress means startup; unreadable progress produces a visible status message while preserving the ability to stop. For an exited job use the refreshed record. |
| 204–209 | Return only status, stage, reason and decision fields. While stopping, replace the stage text with the retained-attempt message. |
| 211–219 | Validate submitted inputs before dispatch. Under the lock, reject closed workspaces and a second active job, after refreshing any finished worker. |
| 221–229 | Create a UTC/random run identifier, ensure the hidden control folder exists, save the validated worker input, and set numerical libraries to one thread in the child environment. |
| 230–234 | Open a retained worker log and launch the shared command with stdout/stderr redirected there. Record the active inputs and flags, then return the current status. |
| 236–249 | Lock stop handling and refresh first. Mark a live job stopped by request, send termination on Windows or interrupt elsewhere, tolerate an already-exited process, then return status. |
| 251–263 | Mark the workspace closed before requesting stop so late start requests are rejected. Wait up to ten seconds, kill a worker that remains, wait for exit, and refresh its retained record under the lock. |
| 266–270 | Define the request handler and suppress routine HTTP access-log noise. |
| 272–285 | Encode JSON without nonfinite values, or send supplied bytes for assets. Set status, media type and length; prohibit caching and type sniffing; constrain page resources to the local origin and deny framing; then write the response body. |
| 287–299 | Allow only this server's loopback host/port and matching optional origin. API calls must also supply its random launch token, compared without a content-dependent early exit. |
| 301–316 | Parse GET paths, enforce local access, capture the workspace, and serve the HTML after inserting the launch token and desktop-mode flag. |
| 318–328 | Route reads for packaged process inspection, saved-run index, live state, desktop sound and a selected saved result. No route here calculates a new run. |
| 329–333 | For report export, validate the selected run's saved manifest before returning the report bytes as UTF-8 Markdown text. |
| 335–344 | Serve only the listed image, CSS, JavaScript and three sound assets, selecting their media type. Return not-found for other paths and readable bad-request responses for file/data errors. |
| 346–357 | Enforce the API token before POST processing. Require JSON and a body between one byte and 512 KB, then decode it. |
| 358–371 | Capture the path, workspace and optional native operations; route native sound/export requests and read-only input inspection. |
| 372–375 | Dispatch a validated new job with HTTP accepted status, or request the active job's stop. |
| 376–384 | Require one to four string run names for comparison, resolve each within the collection, and read verified saved data. Return not-found for unknown routes, conflict for lifecycle errors, and bad-request for malformed data/files. |
| 387–398 | Validate the port, bind the standard threaded server only to loopback, and create its launch token and workspace. If workspace setup fails, close the socket before propagating the error. |
| 401–406 | Create the browser service and print its actual local address and run collection. |
| 407–417 | Optionally open the browser, serve requests until interrupted, and always close the workspace and socket, including browser-launch or shutdown errors. |

## `src/ald_twin/ui/workspace.js`

| Lines | What they do and why |
|---|---|
| 1–14 | State the presentation boundary, define element lookup, read the launch token/desktop flag, collect the four recipe fields and map saved recipe decisions to readable labels. |
| 16–32 | Name the fixed numbers: unit conversions, the 512 KB input limit, the 180 ms validation delay, the one-second poll and download-link times, and the two sound volumes. |
| 34–58 | Initialize process/run lists, draft/inspection/displayed records, activity flags, request counters, pending timers and sound state. Restore browser sound preference when storage is available. |
| 60–70 | Send token-protected GET or JSON POST requests, decode the JSON response, throw a useful error on failure and return successful data. |
| 72–84 | Clear the error panel, hide it for an empty list, and append each error as text in a list item. Text insertion prevents file/input content from becoming page markup. |
| 86–91 | Report whether a value is a plain JSON object rather than null, an array or a primitive. |
| 93–105 | Play only when sounds are enabled. Stop the previous cue, load the selected local WAV, use quiet fixed volumes and report playback failure without touching calculation state. |
| 107–111 | Update the single sound button's wording and accessible pressed state. |
| 113–125 | Disable Run while busy, validating, disconnected or invalid; update its label and Stop visibility. Lock input/process/result selection while starting/running, show activity, and allow report saving only for ready output. |
| 127–145 | Format ordinary values, fractions as percentages, and purge seconds as milliseconds. Keep unavailable values and uncleared purges distinct; zero remains a real number. |
| 147–162 | Replace a table body, then append one row per supplied record and one text cell per value. The nested loops follow the table's rows and columns. |
| 164–181 | Define the six existing output quantities and their display conversion, then produce two value columns with explicit unavailable entries when a model is missing. |
| 183–193 | Recursively preserve array order and sort object keys for comparison; pass primitive values through. Key order alone must not make saved and draft inputs appear different. |
| 195–202 | Show the draft warning only when a displayed result exists and its saved inputs differ from current inputs. |
| 204–214 | Build the compact reactor summary, converting length/gap to millimeters and temperature to Celsius while retaining pressure in pascals. |
| 216–221 | Sum the returned segment durations into the total cycle time. |
| 223–255 | Read available channel, chemistry and diffusion objects. Build the explicit input/value/unit rows, including reference conditions, capacity, rates, grids and optional film density, then render them. |
| 257–269 | Rebuild the reactor summary as label/value pairs with text nodes and show the process name. |
| 271–280 | Display each provenance source and validity statement as text. |
| 282–298 | Display residence time and total cycle time from Python's inspection result. Size the four sequence bars from draft duration ratios and refresh the draft warning. |
| 300–323 | Number each validation request and mark inspection pending. Apply only the latest response/error; an older request cannot replace a newer validation decision or re-enable controls prematurely. |
| 325–333 | Clone selected/imported inputs, populate the four recipe fields, update the selected process button, and request Python validation. |
| 335–342 | Anchor the first axis label at its start, the last at its end and the others at their middle. |
| 344–372 | Draw only a visible saved profile. Set plot dimensions, include any mixed reference in the vertical range, add readable padding, and map saved position/turnover to SVG coordinates using the saved channel length. Clear the previous plot. |
| 374–380 | Define a small SVG helper that creates a namespaced element, applies its attributes, adds optional text and appends it to the chart. |
| 382–411 | Label turnover; draw four horizontal guides and a width-dependent number of position ticks. Add the millimeter axis label, optional dashed mixed reference and blue spatial path using the saved samples. |
| 413–429 | Read only the displayed saved record. Show available model output or the empty-state message; label the run origin, numerical decision, recipe decision and verified-grid status independently. |
| 431–456 | Show an available profile, six metrics, film status, failure reason and retained attempt rows. Fill optional spread/purge diagnostics, then refresh the draft warning, controls and chart. |
| 458–471 | Number a saved-result selection, fetch its verified response and ignore stale selections. Adopt its saved inputs only when requested; check again after validation before updating the selected run and display. |
| 473–477 | Build a saved-run label from process ID, local time (or run ID) and its retained status. |
| 479–486 | Replace a dropdown's options while preserving its prior choice if that run remains present. |
| 488–498 | Refresh the run index and saved-run picker. Use manifest-bearing runs for comparison choices, update the comparison prompt, and retain the displayed run's selection. Opening/comparing still verifies the files. |
| 500–526 | Capture the two comparison choices, hide stale output, fetch the saved comparison and ignore a response for changed choices. Render process, ordered recipe, independent decisions and spatial metrics; display errors only for the still-current pair. |
| 528–538 | Select one Results/Inputs/Compare view, update tab pressed states, hide other views and redraw the plot if visible. |
| 540–553 | In desktop mode request a native export and report errors. In a browser create a temporary download URL and link, trigger its download, then release the URL after one second. |
| 555–567 | Capture the job counter, request live state, ignore an older job response, restore connected status and update activity/stage/Stop controls. Remember the current running job ID. |
| 568–586 | Handle each observed completion once. Refresh saved runs, ignore completion continuation if the user changed selection or started another job, then open the finished output. Play completion only for ready artifacts of the same job. Report errors or disconnection, then schedule the next poll one second later. |
| 588–601 | Choose each process button's title and its explicit synthetic/DEZ-placeholder subtitle. |
| 603–617 | Construct one plain process button per packaged process. |
| 618–634 | On process selection, invalidate old result requests, clear the displayed selection, validate the selected process and show its latest saved result without replacing the new draft. Ignore continuation after a newer selection. |
| 636–642 | Restore native sound preference when applicable, label the toggle, fetch packaged processes, add their buttons and load saved runs. |
| 644–661 | Load live state. Restore active-job inputs when running; otherwise choose the packaged ZnO example or first available process. Open matching saved output if available, retain error visibility, and begin polling. |
| 663–683 | Remember the prior sound choice and disable the toggle while saving so requests cannot arrive out of order. Update its label, save the native preference when applicable, then the browser preference. Restore the prior choice and show an error if saving fails; always re-enable the toggle. Play the click or stop current audio according to the final choice. |
| 685–689 | Wire the three view buttons to view selection and the optional click cue. |
| 691–701 | Repair a missing/malformed recipe object, store the edited duration as a number or null, invalidate prior inspection and disable Run. Wait 180 ms after the latest edit before validating, avoiding a request for every keystroke. |
| 703–716 | Wire saved-result selection and its errors, both comparison dropdowns and the Open inputs button's file chooser. |
| 717–733 | Read one selected JSON file up to 512 KB, require an object, invalidate older selections, clear prior output and validate/show its inputs. Report parsing/data errors and clear the file control so the same file can be reopened. |
| 735–738 | Export a formatted copy of the current inputs, including recipe edits. |
| 740–751 | Capture the displayed run ID, fetch its verified report with the launch token, export that report under the captured run name and display any error. Changing selection while downloading cannot relabel the report. |
| 753–773 | Invalidate old job/selection responses, lock controls during startup and clear old errors. Start the shared worker; retain its ID, select Results and show/play startup feedback. Always finish the startup state and invalidate earlier polls. |
| 775–785 | Disable Stop during its request, show the retained-attempt message on success and restore the control if the request fails. |
| 787–792 | Redraw when the chart changes size, then initialize the workspace with a visible startup error if loading fails. |

## `src/ald_twin/ui/index.html`

| Lines | What they do and why |
|---|---|
| 1–12 | Define an English HTML page with UTF-8 and responsive viewport, placeholders for its launch token/desktop mode, its title, shared stylesheet and deferred JavaScript. |
| 13–20 | Open the page/workspace and its header, showing the lily logo, the workspace name, flexible spacing and one initially-off accessible sound toggle. |
| 21–27 | Define Open inputs and its hidden JSON chooser, the process label, disabled report/run controls and initially hidden Stop. JavaScript enables controls only when their prerequisites hold. |
| 28–36 | Define the project sidebar with process buttons, a labeled saved-result picker, compact reactor values. The repeated lower-left limits block is removed. |
| 37–43 | Open the main workspace and its three accessible view buttons, initially selecting Results. |
| 44–52 | Start Results with its saved-origin label and initially hidden model data. Provide verified-grid text, the spatial/mixed legend and an accessible SVG plot. |
| 53–60 | Provide the two-model metric table, film explanation, empty-state/failure text and collapsed numerical diagnostics/attempt table, then close Results. |
| 61–66 | Define the initially hidden Inputs view, Save inputs button, input/value/unit table and collapsed sources/model-scope disclosure. |
| 67–74 | Define the initially hidden comparison view with two labeled choices, an empty-state prompt and table; close the main workspace. |
| 75–78 | Open the Recipe inspector and its input container. |
| 79–82 | Define A pulse, A purge, B pulse and B purge numeric fields with explicit accessible residence-time labels, nonnegative input bounds and unrestricted decimal steps. Python still performs the authoritative validation. |
| 83–85 | Add four decorative duration bars, their sequence labels and the calculated recipe-time text; close the recipe inputs. |
| 86–88 | Show separate displayed-result numerical and recipe decisions plus the fixed blocked physical-fit status; close the inspector and body layout. |
| 89–93 | Provide the initially hidden draft warning, accessible validation alerts, indeterminate activity bar and live status footer. The repeated model-scope tagline is removed. |
| 94–96 | Close the workspace container, body and document. |

## `src/ald_twin/ui/workspace.css`

| Lines | What they do and why |
|---|---|
| 1–3 | Use a light page background and remove the browser's default body margin. |
| 5–6 | Define the approved blue/gray palette, spacing, forced light controls, system font, ink, white workspace and border. |
| 7–10 | Include borders/padding in sizes, make hidden elements reliably disappear, and give controls the shared font/color with nearly square corners. |
| 11–14 | Style buttons, hover and disabled states; give inputs/selects white backgrounds, plain borders and compact padding. |
| 15–16 | Set checkbox/range appearance. These retained selectors do not add controls to the page. |
| 17–22 | Lay out the light header, lily logo, app name, optional preview text and flexible spacer. The preview selector has no active element. |
| 23–26 | Arrange the wrapping toolbar, subdued process text and pale-blue primary action. |
| 27–32 | Lay out sidebar, flexible center and inspector columns; style the sidebar, uppercase panel title and group labels. |
| 33–35 | Make process choices full-width, square and left-aligned; mark selection with blue fill/border and keep subtitles subdued. |
| 36–39 | Pad property panels, arrange label/value pairs in two columns, mute labels and align numeric glyph widths. |
| 40–41 | Style small supporting notes. |
| 42–47 | Keep the center white, arrange tabs, mark the active tab with a blue underline and pad each view. |
| 48–50 | Align wrapping heading rows and define compact heading/metadata text. |
| 51–57 | Arrange the plot legend and solid/dashed swatches; size the SVG to its panel and style its labels. |
| 58–63 | Allow horizontal table scrolling, collapse borders, style headers/cells, align numbers right and labels left, and let label text wrap. |
| 64–66 | Use amber for review/unverified decisions and green for passed decisions. The saved record chooses the class. |
| 67–71 | Give the inspector a pale panel/divider and align each recipe label, numeric field and unit. |
| 72–74 | Draw the four duration segments with small gaps; pulse segments are blue and purge segments gray. JavaScript replaces initial proportions with draft values. |
| 75–77 | Divide and space the separate result decisions, with modest emphasis on their values. |
| 78–83 | Style the wrapping status footer, thin activity track, its moving element, amber draft warning and red error text. The later activity rule replaces the initial zero width. |
| 84–87 | Permit input-table text to wrap and style compact instructional/empty-state text. |
| 88–94 | Below 870 pixels, reduce the sidebar and place the recipe inspector across the bottom in three sections, adjusting dividers. |
| 95–111 | Below 540 pixels, stack the workspace, compact the header/tables/tabs, put process buttons side by side, hide less-used sidebar groups and enlarge recipe fields. The later rule restores the saved-run picker. |
| 112–118 | Enlarge touch controls and input text for coarse pointers. Disable transitions when reduced motion is requested. |
| 119–123 | Fill the viewport, reserve body height beneath surrounding controls and size the saved-run dropdown within the sidebar. |
| 124–128 | Arrange the two comparison selectors with equal widths and make long saved-origin labels wrap. |
| 129–135 | Style validation alerts and their lists, compact disclosure sections, clickable summaries and wrapping source text. |
| 136–139 | Replace the initial activity width with a moving 30% segment, highlight the enabled sound toggle and define the movement. It indicates activity, not a percentage complete. |
| 140–146 | On narrow screens remove the large body minimum, restore the saved-run picker below process buttons and stack comparison choices at full width. |
| 147–148 | For reduced motion, stop activity animation and show a static full-width activity strip. |
