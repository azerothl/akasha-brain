"""Point d’entrée MCP utilisable depuis le répertoire de travail d’un agent."""

from pathlib import Path
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from akasha_brain.mcp_server import main

    main()
