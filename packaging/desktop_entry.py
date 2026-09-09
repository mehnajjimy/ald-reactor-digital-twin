"""pyinstaller entry point; --worker keeps calculation children out of the ui."""

from ald_twin.desktop import main

raise SystemExit(main())
