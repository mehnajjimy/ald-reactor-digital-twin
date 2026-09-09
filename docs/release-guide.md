# Small updates and releases

The browser interface reads the installed HTML/CSS/JavaScript. Edit the source,
restart its service when Python changes, and refresh the browser. The Mac app
contains a frozen copy; it needs a new verified bundle before edits appear there.
The existing ALD logo and one sound on/off control are unchanged in version 0.1.2.

## Update check

Use **Help → Check for Updates…** in the desktop app. Version 0.1.2 checks
`mehnajjimy/ald-reactor-digital-twin`. Until a stable release is published, it
reports that no public release was found. A source push alone is not a release.

The manual check reads GitHub's latest published stable release. Use tags such as
`v0.1.2`; only three-part numeric versions are supported. Drafts and prereleases
are excluded. A newer version offers to open its GitHub download page in the
browser. Downloads, installation and restarts remain manual.

The request runs outside the interface thread with a five-second socket timeout
and a 1 MB response limit. Duplicate clicks share one check. Closing the app does
not wait for this daemon thread and suppresses a late result. No startup checks,
background polling, credentials, run data or automatic installation are involved.
Unavailable releases, network failures and rate limits are reported separately
from an up-to-date result.

## Source and package

1. Edit the owning file and update its explanation in the [code guide](code-guide.md).
2. Change `__version__` in `src/ald_twin/__init__.py`. The wheel and both Mac bundle
   version fields read it. Keep `CITATION.cff`'s version in sync.
3. Run the Python suite and `node --test tests/workspace.test.cjs`. For a dependency
   change, regenerate notices into a new directory with the pinned build Python:
   `python packaging/collect_licenses.py work/next-licenses`. Compare the result
   with `licenses/bundled` and review the interpreter/asset notices too.
4. Build using the [desktop guide](desktop-guide.md), retaining the prior bundle.
   Check the actual app, its frozen worker, saved source hashes and native dialogs.
5. Replace the installed copy only after verification. Keep the previous copy for
   rollback and record the new evidence without overwriting older checkpoints.

The MIT license covers original project code/documentation. Third-party notices
remain in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and `licenses/`.
The [references](references.md) explain the scientific sources and their limits.
The citation currently uses the owner's `mehnajjimy` handle. Replace it with the
preferred author name if desired; the public repository is recorded, and a release date should be added when
a release exists. No DOI or publication date is invented.

The clean public source folder excludes internal checkpoints, supplied recordings,
private archives and local results. Its generated sounds differ from the personal
installed app's recordings. Build public binaries from that folder. Public Mac
signing/notarization remains release work. Nothing in this guide authorizes a push, publication or scientific
campaign. DEZ inputs remain synthetic placeholders.
