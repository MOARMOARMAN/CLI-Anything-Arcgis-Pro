# CLI-Anything · ArcGIS Pro

> Making ArcGIS Pro agent-native. A companion harness for
> [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — the **closed-source**
> counterpart to its QGIS CLI.

ArcGIS Pro is Esri's commercial, closed-source GIS desktop app, so it can't be
auto-generated from source like CLI-Anything's other harnesses. This project
wraps ArcGIS Pro's **official ArcPy / Pro SDK** instead, in two complementary modes:

| Mode | What it drives | How |
|---|---|---|
| **Headless CLI** | `.aprx` projects & geodatabases on disk | `pip` package, `arcpy` |
| **Live bridge + MCP** | the **open** ArcGIS Pro session (you watch it work) | in-process .NET add-in + MCP server |

## Why two modes

- The **headless CLI** is perfect for batch/automation: export 300 maps, run a
  geoprocessing pipeline, query a geodatabase — no GUI needed.
- ArcPy can't attach to a *running* ArcGIS Pro from an external process (Esri
  limitation). To let an agent operate the **live** project — and let the user
  **watch** it happen in the window — the **live bridge** runs an in-process
  add-in that exposes the open project over a local socket, wrapped as MCP tools.

```
Agent ──MCP──► mcp_server.py ──HTTP─► in-Pro add-in ──QueuedTask─► LIVE project
                                                                     (you watch)
```

## Install (headless CLI)

Install into ArcGIS Pro's bundled Python (`arcgispro-py3`), which provides ArcPy:

```bat
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" -m pip install ^
  git+https://github.com/Jasper0122/CLI-Anything-Arcgis-Pro.git
```

Then:

```bat
cli-anything-arcgis-pro --json info
```

**Installed into a different Python?** (e.g. via the CLI-Hub, which installs with
its own interpreter.) That's fine — the `cli-anything-arcgis-pro` command
**self-dispatches** into ArcGIS Pro's `arcgispro-py3` interpreter when ArcPy isn't
present in the current one. It locates Pro via common install paths, the
`SOFTWARE\ESRI\ArcGISPro` registry key, or the `CLI_ANYTHING_ARCGIS_PYTHON`
environment variable (set this to override).

Requires: a licensed **ArcGIS Pro** install (provides ArcPy). Verified on ArcGIS
Pro 3.4 / ArcPy 3.4.3 / .NET 8.

## Headless CLI commands

| Command | What it does |
|---|---|
| `info` | ArcPy version, license level, extension availability. |
| `project inspect / layers` | Maps, layouts, layers, data sources of an `.aprx`. |
| `layout list / export / mapseries` | ★ Professional export: layouts + Map Series / map books (the ArcGIS Pro edge over QGIS). |
| `data describe / fields / count / query / calc` | Inspect & edit feature classes and tables. |
| `gp <tool> -a … --kw k=v` | Run any geoprocessing tool (the whole ArcToolbox). |
| `batch export-layouts` | Export every layout in a project. |

Every command supports `--json` (place it before the subcommand) and returns
`{"ok": …, "data"|"error": …}`. See [`SKILL.md`](SKILL.md) for the full agent guide.

```bat
:: print-quality A0 map at 300 DPI
cli-anything-arcgis-pro --json layout export C:\proj\city.aprx --layout "Poster" --out C:\out\poster.pdf --dpi 300

:: buffer roads by 100 m
cli-anything-arcgis-pro --json gp analysis.Buffer -a C:\d.gdb\roads -a C:\d.gdb\roads_buf --kw buffer_distance_or_field="100 Meters"
```

## Live bridge + MCP

See [`live-bridge/README.md`](live-bridge/README.md). It builds an ArcGIS Pro
add-in that hosts a loopback server inside Pro, plus a dependency-free MCP server
(`live-bridge/mcp_server.py`). Once registered with an MCP client, an agent gets:

| MCP tool | Action on the **live** project |
|---|---|
| `arcgis_ping` | Read the open project: maps, layouts, active view. |
| `arcgis_export_layout` | Export a layout to PDF. |
| `arcgis_zoom_to` | Zoom the active map to a layer (optionally a selection). |
| `arcgis_query` | Query a layer's attributes → structured rows. |
| `arcgis_run_gp` | Run **any** geoprocessing tool; outputs are added to the live map. |

## Repository layout

```
cli_anything_arcgis_pro/   headless ArcPy CLI (pip package)
tests/                     test_core.py (no backend) + test_full_e2e.py (needs Pro)
live-bridge/
  mcp_server.py            stdlib-only MCP server → in-Pro bridge
  ProSimpleMapExport/      ArcGIS Pro .NET add-in (bridge server + export button)
SKILL.md                   canonical agent skill definition
```

## License

[Apache-2.0](LICENSE), matching upstream CLI-Anything.

## Acknowledgements

Built as a contribution to [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything)
("Making ALL Software Agent-Native"). ArcGIS, ArcGIS Pro and ArcPy are trademarks
of Esri; this project is an independent integration and is not affiliated with Esri.
