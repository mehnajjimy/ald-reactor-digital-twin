"""pyinstaller entry point. --worker keeps calculation children out of the ui."""

from ald_twin.desktop import main

# run the desktop app and pass its exit code to the os
raise SystemExit(main())
