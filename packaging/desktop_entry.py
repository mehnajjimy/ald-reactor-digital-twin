"""PyInstaller entry point; --worker keeps calculation children out of the UI."""
from ald_twin.desktop import main

raise SystemExit(main())
