# Install ALD Reactor

**[Download 1.0.0 for Mac](https://github.com/mehnajjimy/ald-reactor-digital-twin/releases/download/v1.0.0/ALD-Reactor-1.0.0-macOS-arm64.zip)** · [All releases](https://github.com/mehnajjimy/ald-reactor-digital-twin/releases)

The desktop app includes Python and the solver. No terminal setup is needed.

**Tested only on an Apple Silicon Mac running macOS 26.6.2.** The build targets
macOS 14 or later, but older macOS versions have not been tested. There is no
verified Windows or Intel Mac app. The Python source also runs through Linux CI.

## Install

1. Download the Mac ZIP above and double-click it to unzip.
2. Drag **ALD Reactor.app** into **Applications**.
3. Open **ALD Reactor** from Applications.

This release is ad-hoc signed, without an Apple Developer ID or notarization.
If macOS blocks it because the developer cannot be verified, and you trust this
download, open **System Settings → Privacy & Security → Open Anyway** after
trying to launch the app. Confirm **Open** when prompted.
See [Apple's instructions](https://support.apple.com/en-us/102445).

Choose the ZIP named **ALD-Reactor-1.0.0-macOS-arm64.zip** under release assets.
GitHub's **Source code** archives contain the project, not the built app.
The release also includes a SHA-256 checksum file for checking the download.

## First run

Choose a process, review its inputs and select **Run**. The examples are synthetic;
DEZ transport values remain placeholders. Numerical acceptance does not establish
experimental validity or guarantee a feasible recipe.

The app saves runs and settings under
`~/Library/Application Support/ALD Reactor/` by default. **File → Open runs folder…**
lets you choose another collection. **Stop** ends an active calculation; quitting
also stops its worker. Completed records remain available.

## Updates

Use **Help → Check for Updates…** to open a newer release's download page. Quit
the app, download the new Mac ZIP and replace the copy in Applications. Updates
are manual. Saved runs stay in their own folder; replacing the app preserves them.

For the browser interface or CLI, follow [source installation](installation.md).
Build instructions are in the [desktop guide](desktop-guide.md).
