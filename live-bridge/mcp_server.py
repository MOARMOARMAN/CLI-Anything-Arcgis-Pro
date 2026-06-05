"""MCP server bridging Claude Code to the LIVE ArcGIS Pro session.

Architecture:
    Claude Code  --stdio JSON-RPC-->  this server  --HTTP-->  ProSimpleMapExport
    add-in (inside ArcGIS Pro, 127.0.0.1:5005)  -->  live project (QueuedTask).

Zero third-party deps: implements the MCP stdio protocol by hand using only the
standard library, so it runs on any Python 3 without `pip install`.
"""

import os
import sys
import json
import urllib.request
import urllib.error

# Where the in-Pro add-in bridge listens. Override with ARCGIS_BRIDGE_URL when the
# server and ArcGIS Pro are on different hosts (e.g. running this in a container).
BRIDGE_URL = os.environ.get("ARCGIS_BRIDGE_URL", "http://127.0.0.1:5005/")

# --- Deny-by-default deletion guard -----------------------------------------
# Block any geoprocessing tool whose name looks destructive (Delete*/Truncate*)
# unless the caller explicitly opts in via an `allow_delete` argument or the
# ARCGIS_CLI_ALLOW_DELETE environment variable. Stops run_gp from deleting
# shapefiles / feature classes / geodatabase contents by default.
_DESTRUCTIVE_TOOL_TOKENS = ("delete", "truncate")
_TRUTHY = {"1", "true", "yes", "on", "y", "t"}


def _deletion_allowed(args):
    if str((args or {}).get("allow_delete", "")).strip().lower() in _TRUTHY:
        return True
    return os.environ.get("ARCGIS_CLI_ALLOW_DELETE", "").strip().lower() in _TRUTHY


def _is_destructive_tool(tool):
    t = (tool or "").lower()
    return any(tok in t for tok in _DESTRUCTIVE_TOOL_TOKENS)


def log(msg):
    print(f"[arcgis-mcp] {msg}", file=sys.stderr, flush=True)


def call_bridge(payload, timeout=180):
    """POST a command to the in-Pro bridge and return its parsed JSON."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_URL, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "error": (
                f"无法连接 ArcGIS Pro 桥 ({BRIDGE_URL}): {e}. "
                "请确认 ArcGIS Pro 正在运行且已加载 ProSimpleMapExport add-in。"
            ),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"桥调用失败: {e}"}


TOOLS = [
    {
        "name": "arcgis_ping",
        "description": (
            "Read the state of the currently open ArcGIS Pro project. Gather the following details: "
            "Project name, all maps, all layouts, and currently active map/layout. "
            "Call this tool before using other tools to discover what project is open and details about the project."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "arcgis_export_layout",
        "description": (
            "Export a specific layout of the currently live ArcGIS Pro Project to a PDF file. "
            "Export in the user's currently open ArcGIS Pro instance so they can watch it happen. "
            "Return the output path and the file size."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {
                    "type": "string",
                    "description": (
                        "Absolute return path for output PDF. "
                        r"For example C:\temp\map.pdf"
                    ),
                },
                "layout": {
                    "type": "string",
                    "description": (
                        "Name of layout to export (Optional) "
                        "If left empty, default to active layout or the first layout if no currently active layout"
                    ),
                },
                "dpi": {
                    "type": "integer",
                    "enum": [72, 96, 150, 200, 300, 400, 600, 1200],
                    "default": 300,
                    "description": (
                        "Export resolution in DPI. Defaulted to 300"
                    )
                },
            },
            "required": ["out"],
        },
    },
    {
        "name": "arcgis_zoom_to",
        "description": (
            "Zoom the active Map view to a specific feature layer. (the user should see the map pan/zoom in their application window). "
            "Optional 'where' parameter: selects matching features first, then zooms into that specific section. "
            "Requires ArcGIS Pro to be in Map view, not Layout view."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "description": (
                        "Name of feature layer to zoom to."
                    )
                },
                "where": {
                    "type": "string",
                    "description": (
                        "Optional SQL Parameter: For example \"POP > 1000\". "
                        "If provided, matching features are selected, then view is zoomed to selection."
                    )
                },
            },
            "required": ["layer"],
        },
    },
    {
        "name": "arcgis_query",
        "description": (
            "Queries attributes of the feature layer of the currently live ArcGIS project and returns in structured rows (excluding geometry). "
            "Supports filtering through 'where' parameter and limiting returned row counts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string", "description": "The name of target Feature Layer. "},
                "where": {"type": "string", "description": "Optional: SQL query 'where' parameter used to filter the features"},
                "map": {
                    "type": "string",
                    "description": (
                        "The name of the map (Optional) "
                        "If left empty, default to current active map and if no map is currently active, fall back to the first map."
                    )
                },
                "limit": {
                    "type": "integer", 
                    "default": 50,
                    "minimum": 0,
                    "description": (
                        "Limit on returned rows. "
                        "Defaults to 50; "
                        "Set to 0 for unlimited rows."
                    )
                },
            },
            "required": ["layer"],
        },
    },
    {
        "name": "arcgis_run_gp",
        "description": (
            "Execute any ArcGIS geoprocessing tool on the live project. "
            "(Supports the entire ArcToolbox: analysis, management, conversion, sa, etc.) "
            "Output layers will be automatically added to the current active map. (This process is visible to the user). "
            "Specify tool usage utilizing dot notation ('toolbox_alias.Toolname'). For example: 'analysis.Buffer', 'management.Clip'; "
            "The 'params' field is an ordered array of positional argument strings. "
            "The ordering must exactly match the tool's official ArcToolbox function signature. "
            "Example: tool='analysis.Buffer', params=['roads','roads_buf','100 Meters']."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "description": "Tool name in dot notation, e.g. 'analysis.Buffer', 'management.Dissolve', 'sa.Slope'",
                },
                "params": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "An ordered array of positional argument strings that follow the ordering of the tool's official ArcToolbox function signature. "
                        "Inputs and outputs are strongly recommended to use absolute dataset paths. (Example: C:\\...\\x.gdb\\fc) "
                        "as short layer names are unreliable in the background geoprocessing environment. "
                        "Distance or value parameters should include units (e.g., '500 Meters') when applicable."
                    ),
                },
                "allow_delete": {
                    "type": "boolean",
                    "default": False, 
                    "description": (
                        "Safety opt-in. Destructive tools (Delete*/Truncate*) are BLOCKED by "
                        "default to protect shapefiles, feature classes and geodatabases. Set "
                        "true ONLY when you intend to delete or truncate data."
                    ),
                },
            },
            "required": ["tool", "params"],
        },
    },
    {
        "name": "arcgis_symbology",
        "description": (
            "Applies a symbology render to a specific feature layer within the currently active project and "
            "instantly updates the visual display within the ArcGIS Pro window. "
            "Supported renderers: "
            "'graduated' uses a numerical field for classified color styling. "
            "'unique' uses categorical fields for distinct colors for each unique value. "
            "Example: layer='tracts', renderer='graduated', field='MEDINCOME', classes=5, ramp='Viridis'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string", "description": "The name of the target feature layer to be rendered."},
                "renderer": {
                    "type": "string",
                    "enum": ["graduated", "unique"],
                    "description": (
                        "The types of symbology renderers to apply. "
                        "'graduated' uses numerical field for classified color styling. "
                        "'unique' assigns distinct color to each unique categorical value."
                    )
                },
                "field": {
                    "type": "string",
                    "description": (
                        "The name of the attribute field used for rendering. "
                        "'graduated' required a numerical field; "
                        "'unique' requires a categorical field."
                    )
                },
                "classes": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 32,
                    "default": 5,
                    "description": (
                        "The number of classification classes. Applicable to 'graduated' rendering. Ignored for 'unique' rendering. "
                        "(Defaults to 5)"
                    )
                },
                "method": {
                    "type": "string",
                    "default": "NaturalBreaks",
                    "enum": [
                        "NaturalBreaks",
                        "EqualInterval",
                        "Quantile",
                        "GeometricInterval",
                        "StandardDeviation",
                    ],
                    "description": (
                        "The classification methods: "
                        "Defaults to NaturalBreaks - Good for unevenly distributed data. "
                        "Equal Interval - Good for Uniform ranges/percentages. "
                        "Quantile - Good for well-distributed or linear data. "
                        "GeometricInterval - Good for Highly skewed data. "
                        "StandardDeviation - Good for highlighting anomalies in the data. "
                        "Ignored for 'unique' rendering."
                    )
                },
                "ramp": {
                    "type": "string", 
                    "description": (
                        "The name of the color ramp to apply (Optional). "
                        "Example: 'Viridis'"
                    )
                },
                "map": {
                    "type": "string", 
                    "description": (
                        "The name of the map (Optional) "
                        "If left empty, default to current active map and if no map is currently active, fall back to the first map."
                    )
                },
            },
            "required": ["layer", "renderer", "field"],
        },
    },
]


def handle(req):
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        client_ver = (req.get("params") or {}).get("protocolVersion", "2024-11-05")
        return ok(rid, {
            "protocolVersion": client_ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "arcgis-pro-bridge", "version": "1.0.0"},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response

    if method == "ping":
        return ok(rid, {})

    if method == "tools/list":
        return ok(rid, {"tools": TOOLS})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        command_map = {
            "arcgis_ping": "ping",
            "arcgis_export_layout": "export_layout",
            "arcgis_zoom_to": "zoom_to",
            "arcgis_query": "query",
            "arcgis_run_gp": "run_gp",
            "arcgis_symbology": "symbology",
        }
        cmd = command_map.get(name)
        if cmd is None:
            return err(rid, -32601, f"unknown tool: {name}")
        # Deny-by-default: block destructive geoprocessing unless explicitly allowed.
        if cmd == "run_gp" and _is_destructive_tool(args.get("tool")) and not _deletion_allowed(args):
            blocked = (
                f"Refused to run destructive tool {args.get('tool')!r}: it deletes or truncates "
                "data (shapefiles, feature classes, geodatabase contents) and is blocked by "
                "default. To proceed intentionally, set allow_delete=true in the tool arguments "
                "or set ARCGIS_CLI_ALLOW_DELETE=1 in the server environment."
            )
            return ok(rid, {"content": [{"type": "text", "text": blocked}], "isError": True})
        payload = {"command": cmd}
        payload.update(args)
        result = call_bridge(payload)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return ok(rid, {
            "content": [{"type": "text", "text": text}],
            "isError": not result.get("ok", False),
        })

    if rid is not None:
        return err(rid, -32601, f"method not found: {method}")
    return None


def ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


# BOM / zero-width codepoints some pipes prepend to the first line.
_BOM_CODEPOINTS = (0xFEFF, 0xFFFE, 0x200B)


def main():
    # Claude Code speaks UTF-8 over stdio. On a non-UTF-8 locale (e.g. Chinese GBK)
    # Python would otherwise mis-decode the stream — force UTF-8 both ways.
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    log(f"started, bridging to {BRIDGE_URL}")
    for raw in sys.stdin:
        line = raw.strip()
        while line and ord(line[0]) in _BOM_CODEPOINTS:
            line = line[1:]
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:  # noqa: BLE001
            log(f"bad json: {e}")
            continue
        try:
            resp = handle(req)
        except Exception as e:  # noqa: BLE001
            rid = req.get("id")
            resp = err(rid, -32603, str(e)) if rid is not None else None
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
