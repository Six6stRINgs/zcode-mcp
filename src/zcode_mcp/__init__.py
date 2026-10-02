"""zcode-mcp: MCP gateway into ZCode desktop conversations.

Speaks MCP (JSON-RPC 2.0 over stdio) to any MCP client on one side and the
official ZCode Protocol (NDJSON over stdio, spawned ``zcode app-server``) on
the other, exposing ZCode conversations as tools: create, send (text +
file/image attachments), observe mid-turn (status + streaming output),
read, wait, stop.

See README.md for registration, tools and protocol caveats.
"""

__version__ = "0.10.2"
