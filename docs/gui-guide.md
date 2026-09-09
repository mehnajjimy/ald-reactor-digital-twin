# Reactor workspace

Open **ALD Reactor.app** for the standalone Mac workspace. It manages startup,
shutdown and native file dialogs; see the [desktop guide](desktop-guide.md).
The run controls below are shared by both interfaces.

## Browser startup

Install the project as described in [installation.md](installation.md). On
macOS/Linux, run this from the repository root:

```sh
.venv/bin/ald-twin gui
```

In Windows PowerShell:

```powershell
.\.venv\Scripts\ald-twin.exe gui
```

The command opens the local workspace in your browser. Keep its terminal open.
It uses the same Python solver and numerical checks as `ald-twin simulate`.
The interface is included in the package; it needs no separate web installation.

## A run

1. Choose **ZnO equivalent** or **Fictional A / B**. Use **Open inputs** for a
   compatible process JSON file of your own.
2. Open **Inputs** to inspect values and units. Sources and model scope are in
   the disclosure below the table. Input errors appear before a run can start.
3. Set the four durations in the recipe panel. Values are in carrier residence
   times, τ; the calculated cycle time is shown below. **Save inputs** downloads
   the current JSON, including recipe edits.
4. Select **Run simulation**. The status bar shows actual solver stages, with an
   activity indicator rather than a guessed completion percentage. One run is
   allowed at a time. **Stop** retains completed attempts and marks an unfinished
   run interrupted. A new run starts in a new folder.
5. Read the results and separate numerical/recipe decisions. **Numerical checks**
   expands the attempts and purge diagnostics. **Save report** downloads a copy
   of the verified report without changing the saved original.

**Open a result** loads a saved run and its inputs. Editing those inputs keeps
the displayed result unchanged and labels the difference. **Compare** reads two
selected completed runs without recalculating. Unverified results retain their
status; interrupted records have no completed manifest and cannot be compared.
An altered saved artifact is rejected rather than silently accepted.

**Sounds on/off** is the only sound control. The choice is remembered in the
app or browser. Clicks are quiet; the crystal cue accompanies a run start and the
completion cue accompanies finished, verified artifact writing. Completion does
not mean the recipe passed. Nothing plays on hover; opening a saved run has no
completion cue.

## Local files and shutdown

In the desktop app, use **File → Open runs folder…** and **File → Show runs folder**.
Closing its window stops the service and worker. The paragraphs below describe
the browser command.

The default folder is `runs/` under the directory where you start the command.
To open another existing run collection, supply its folder:

```sh
.venv/bin/ald-twin gui --runs /absolute/path/to/runs
```

The workspace lists direct child run folders containing `run.json`. Completed
folders retain the CLI's inputs, source snapshots, numerical attempts, report
and manifest. Worker inputs and console logs are in `runs/.gui/`. Do not edit
files inside a completed run; export copies or create a new run instead.

Closing the browser tab leaves the local server and any calculation running.
Reopen the printed address to reconnect. Stop the calculation before closing the
terminal, or press Ctrl+C there to stop the server and its worker. On Windows,
stopping terminates the worker and retains already saved attempts; an attempt
still in memory is not recovered. Windows instructions have not been verified
on this Mac.

If the default port is occupied, use `--port 0` to choose an available local
port. `--no-browser` prints the address without opening a browser automatically.
The server listens only on this computer's loopback address.

The DEZ example remains a synthetic placeholder. Real property integration,
physical fitting and broader chemistry remain separate scientific work.
The three sound cues in this source folder are generated original tones.

## Version 0.1.1

The repeated lower-left limits block is removed; numerical, recipe and physical
status remain separate in the results. The logo and sound toggle are unchanged.
The desktop menu **Help → Check for Updates…** shows the installed version.
The release location is deliberately unset until the owner creates GitHub;
no network request occurs in that state. See the [release guide](release-guide.md).
