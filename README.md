# siglent-sdm-mcp

MCP server for Siglent SDM series digital multimeters (SDM3045X, SDM3055, SDM3065X, SDM4055A, SDM4065A).

## Installation

```bash
pip install siglent-sdm-mcp
```

## Usage

Set the instrument IP and run:

```bash
export SDM_HOST=192.168.1.100
siglent-sdm-mcp
```

Or with `uv`:

```json
{
  "mcpServers": {
    "siglent-sdm": {
      "command": "uvx",
      "args": ["siglent-sdm-mcp"],
      "env": {
        "SDM_HOST": "192.168.1.100"
      }
    }
  }
}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SDM_HOST` | Yes | — | IP address or hostname of the instrument |
| `SDM_PORT` | No | `5024` | TCP port for SCPI communication |

## Tools

| Tool | Description |
|------|-------------|
| `identify` | Get instrument ID (manufacturer, model, serial, firmware) |
| `measure` | One-shot measurement with optional function/range/resolution |
| `configure` | Set measurement function without triggering |
| `read` | Trigger and read using current configuration |
| `get_last_reading` | Get most recent reading without triggering |
| `get_configuration` | Query current measurement setup |
| `set_nplc` / `get_nplc` | Set/query integration time (power line cycles) |
| `set_range` / `get_range` | Set/query measurement range |
| `set_autorange` | Enable/disable autoranging |
| `set_trigger` | Configure trigger source, delay, count |
| `set_sample_count` | Set samples per trigger |
| `monitor` | Fixed-duration repeated measurements (time-series) |
| `scpi_command` | Send arbitrary SCPI commands |
| `reset` | Reset instrument to factory defaults |
| `get_error` | Query error queue |
| `set_display_text` | Show/clear text on instrument display |

## Measurement Functions

`VOLT:DC`, `VOLT:AC`, `CURR:DC`, `CURR:AC`, `RES` (2-wire), `FRES` (4-wire), `FREQ`, `PER`, `CAP`, `TEMP`, `DIOD`, `CONT`

## License

GPL-3.0-or-later
