# Code reading guide

The maintenance code keeps one calculation path: inputs are validated in Python,
the shared solver runs in a child process, and the interface reads saved output.
The guides below explain every nonblank line of the application and packaging
code touched by this maintenance work. Related statements share a short line
range; the source is not duplicated or filled with obvious comments.

- [Inputs and saved calculations](workflow-code-guide.md): validation, units,
  source snapshots, numerical checks, reports and saved-file consistency.
- [Local interface](gui-code-guide.md): server, worker lifecycle, browser state,
  layout and styles.
- [Desktop wrapper](desktop-code-guide.md): native dialogs, settings, startup,
  quit, frozen dispatch and Mac packaging.
- [CLI and package files](cli-package-code-guide.md): commands, installation
  metadata, dependency pins, CI, ignore rules and original public sound cues.

Line numbers describe this reviewed version. Update the affected range when
editing a covered file. Tests explain the failure they guard in their names;
run Python checks with `python -m pytest -q` and interface race checks with
`node --test tests/workspace.test.cjs` (Node 22).

The original scientific modules are unchanged. Their equations, units and
assumptions are described in [input-reference.md](input-reference.md). A passing
calculation is still distinct from a feasible recipe and a valid physical model.
DEZ inputs remain synthetic placeholders.

The [update and license guide](update-code-guide.md) explains the release checker,
shared version and notice collector. See [release steps](release-guide.md).

[README figures](readme-figures.md) explains the saved display data and plotting code.
