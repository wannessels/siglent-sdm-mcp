"""MCP server for Siglent SDM series digital multimeters.

Supports SDM3045X, SDM3055, SDM3065X, SDM4055A, SDM4065A and other
SDM-series instruments that speak SCPI over TCP.

Environment variables:
    SDM_HOST  — IP address or hostname of the instrument (required)
    SDM_PORT  — TCP port (default: 5024)
"""

import asyncio
import json
import os
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from siglent_sdm_mcp.scpi_connection import SCPIConnection

mcp = FastMCP("siglent-sdm")
conn: SCPIConnection | None = None


def _get_conn() -> SCPIConnection:
    global conn
    if conn is None:
        host = os.environ["SDM_HOST"]
        port = int(os.environ.get("SDM_PORT", "5024"))
        conn = SCPIConnection(host, port)
    return conn


# ---------------------------------------------------------------------------
# Valid measurement functions
# ---------------------------------------------------------------------------

FUNCTIONS = {
    "VOLT:DC": "DC Voltage",
    "VOLT:AC": "AC Voltage",
    "CURR:DC": "DC Current",
    "CURR:AC": "AC Current",
    "RES": "2-Wire Resistance",
    "FRES": "4-Wire Resistance",
    "FREQ": "Frequency",
    "PER": "Period",
    "CAP": "Capacitance",
    "TEMP": "Temperature",
    "DIOD": "Diode",
    "CONT": "Continuity",
}

# Longer aliases accepted by the instrument — map to short form
_FUNC_ALIASES = {
    "VOLTAGE:DC": "VOLT:DC",
    "VOLTAGE:AC": "VOLT:AC",
    "CURRENT:DC": "CURR:DC",
    "CURRENT:AC": "CURR:AC",
    "RESISTANCE": "RES",
    "FRESISTANCE": "FRES",
    "FREQUENCY": "FREQ",
    "PERIOD": "PER",
    "CAPACITANCE": "CAP",
    "TEMPERATURE": "TEMP",
    "DIODE": "DIOD",
    "CONTINUITY": "CONT",
}


def _normalize_function(func: str) -> str:
    """Normalize a measurement function string to its short SCPI form."""
    f = func.upper().strip().strip('"')
    if f in FUNCTIONS:
        return f
    if f in _FUNC_ALIASES:
        return _FUNC_ALIASES[f]
    return f  # pass through and let instrument validate


def _scpi_func_for_configure(func: str) -> str:
    """Map short function name to the form used in CONFigure/MEASure commands.

    E.g. "VOLT:DC" stays as-is, "RES" -> "RESistance", "FRES" -> "FRESistance"
    """
    mapping = {
        "VOLT:DC": "VOLTage:DC",
        "VOLT:AC": "VOLTage:AC",
        "CURR:DC": "CURRent:DC",
        "CURR:AC": "CURRent:AC",
        "RES": "RESistance",
        "FRES": "FRESistance",
        "FREQ": "FREQuency",
        "PER": "PERiod",
        "CAP": "CAPacitance",
        "TEMP": "TEMPerature",
        "DIOD": "DIODe",
        "CONT": "CONTinuity",
    }
    return mapping.get(func, func)


def _sense_prefix(func: str) -> str:
    """Return the SENSe subsystem prefix for a function.

    E.g. "VOLT:DC" -> "VOLTage:DC", "RES" -> "RESistance"
    Used for commands like VOLT:DC:NPLC, RESistance:RANGe, etc.
    """
    return _scpi_func_for_configure(func)


# ---------------------------------------------------------------------------
# Identity & System
# ---------------------------------------------------------------------------


@mcp.tool()
async def identify() -> str:
    """Query instrument identification (manufacturer, model, serial, firmware)."""
    return await _get_conn().query("*IDN?")


@mcp.tool()
async def reset() -> str:
    """Reset the instrument to factory default settings."""
    await _get_conn().write("*RST")
    return "Instrument reset to factory defaults"


@mcp.tool()
async def get_error() -> str:
    """Query the instrument error queue. Returns error code and message.

    Returns '0,"No error"' when the queue is empty.
    """
    return await _get_conn().query("SYSTem:ERRor?")


@mcp.tool()
async def set_display_text(text: str = "") -> str:
    """Show a text message on the instrument display, or clear it.

    Args:
        text: Message to display (max ~12 chars). Empty string clears the display.
    """
    if not text:
        await _get_conn().write("DISPlay:TEXT:CLEar")
        return "Display text cleared"
    await _get_conn().write(f'DISPlay:TEXT "{text}"')
    return f"Display text set to: {text}"


# ---------------------------------------------------------------------------
# One-shot measurement
# ---------------------------------------------------------------------------


@mcp.tool()
async def measure(
    function: str = "VOLT:DC",
    range: Optional[str] = None,
    resolution: Optional[str] = None,
) -> str:
    """Take a single measurement. Configures the function, triggers, and returns the reading.

    This is the simplest way to get a reading but slower for repeated measurements.
    For faster repeated reads, use configure() then read().

    Args:
        function: Measurement function. One of: VOLT:DC, VOLT:AC, CURR:DC, CURR:AC,
            RES (2-wire), FRES (4-wire), FREQ, PER, CAP, TEMP, DIOD, CONT.
        range: Measurement range (e.g. "10" for 10V range, "AUTO", "MIN", "MAX").
            Omit for default/auto.
        resolution: Measurement resolution (e.g. "MIN" for best, "MAX" for fastest).
            Omit for default.

    Returns:
        The measurement value in scientific notation (e.g. "+1.23456789E+00").
    """
    func = _normalize_function(function)
    scpi_func = _scpi_func_for_configure(func)
    cmd = f"MEASure:{scpi_func}?"
    params = []
    if range is not None:
        params.append(range)
    if resolution is not None:
        if not params:
            params.append("DEF")  # need range placeholder
        params.append(resolution)
    if params:
        cmd += " " + ",".join(params)
    return await _get_conn().query(cmd)


# ---------------------------------------------------------------------------
# Configure + Read workflow
# ---------------------------------------------------------------------------


@mcp.tool()
async def configure(
    function: str = "VOLT:DC",
    range: Optional[str] = None,
    resolution: Optional[str] = None,
) -> str:
    """Configure measurement function, range, and resolution without triggering.

    After configuring, use read() to take measurements (faster for repeated reads).

    Args:
        function: Measurement function. One of: VOLT:DC, VOLT:AC, CURR:DC, CURR:AC,
            RES, FRES, FREQ, PER, CAP, TEMP, DIOD, CONT.
        range: Measurement range (e.g. "10", "AUTO", "MIN", "MAX"). Omit for default.
        resolution: Measurement resolution. Omit for default.
    """
    func = _normalize_function(function)
    scpi_func = _scpi_func_for_configure(func)
    cmd = f"CONFigure:{scpi_func}"
    params = []
    if range is not None:
        params.append(range)
    if resolution is not None:
        if not params:
            params.append("DEF")
        params.append(resolution)
    if params:
        cmd += " " + ",".join(params)
    await _get_conn().write(cmd)
    return f"Configured for {FUNCTIONS.get(func, func)}" + (f" range={range}" if range else "") + (f" resolution={resolution}" if resolution else "")


@mcp.tool()
async def get_configuration() -> str:
    """Query the current measurement configuration (function, range, resolution)."""
    return await _get_conn().query("CONFigure?")


@mcp.tool()
async def read() -> str:
    """Trigger a measurement and return the reading using the current configuration.

    Use configure() first to set up the measurement function and parameters.
    This is faster than measure() for repeated readings of the same type.

    Returns:
        The measurement value in scientific notation.
    """
    return await _get_conn().query("READ?")


@mcp.tool()
async def get_last_reading() -> str:
    """Get the most recent measurement without triggering a new one.

    Returns the last reading with units suffix (e.g. "-5.21E-04 VDC").
    Requires firmware 3.01.01.10 or later.
    """
    return await _get_conn().query("DATA:LAST?")


# ---------------------------------------------------------------------------
# Measurement parameters
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_nplc(function: str, nplc: float) -> str:
    """Set integration time in power line cycles (NPLC) for a measurement function.

    Lower NPLC = faster but noisier. Higher NPLC = slower but more accurate.
    SDM3000 series: 0.005, 0.05, 0.5, 1, 10, 100 (at 50Hz mains).
    SDM4000A series: 0.001 to 1000.

    Applies to: VOLT:DC, CURR:DC, RES, FRES, TEMP.

    Args:
        function: Measurement function (e.g. "VOLT:DC", "RES").
        nplc: Integration time in PLCs.
    """
    func = _normalize_function(function)
    prefix = _sense_prefix(func)
    await _get_conn().write(f"{prefix}:NPLC {nplc}")
    return f"NPLC set to {nplc} for {FUNCTIONS.get(func, func)}"


@mcp.tool()
async def get_nplc(function: str) -> str:
    """Query the current NPLC setting for a measurement function.

    Args:
        function: Measurement function (e.g. "VOLT:DC", "RES").
    """
    func = _normalize_function(function)
    prefix = _sense_prefix(func)
    return await _get_conn().query(f"{prefix}:NPLC?")


@mcp.tool()
async def set_range(function: str, range: str) -> str:
    """Set the measurement range for a function.

    Args:
        function: Measurement function (e.g. "VOLT:DC", "RES").
        range: Range value (e.g. "10" for 10V, "AUTO", "MIN", "MAX", "DEF").
    """
    func = _normalize_function(function)
    prefix = _sense_prefix(func)
    r = range.upper()
    if r == "AUTO":
        await _get_conn().write(f"{prefix}:RANGe:AUTO ON")
        return f"Autorange enabled for {FUNCTIONS.get(func, func)}"
    await _get_conn().write(f"{prefix}:RANGe {range}")
    return f"Range set to {range} for {FUNCTIONS.get(func, func)}"


@mcp.tool()
async def get_range(function: str) -> str:
    """Query the current measurement range and autorange state.

    Args:
        function: Measurement function (e.g. "VOLT:DC", "RES").

    Returns:
        JSON with range value and autorange state.
    """
    func = _normalize_function(function)
    prefix = _sense_prefix(func)
    c = _get_conn()
    range_val = await c.query(f"{prefix}:RANGe?")
    try:
        auto = await c.query(f"{prefix}:RANGe:AUTO?")
    except Exception:
        auto = "N/A"
    return json.dumps({"range": range_val, "autorange": auto})


@mcp.tool()
async def set_autorange(function: str, enabled: bool = True) -> str:
    """Enable or disable autoranging for a measurement function.

    Args:
        function: Measurement function (e.g. "VOLT:DC", "RES").
        enabled: True to enable autorange, False to disable.
    """
    func = _normalize_function(function)
    prefix = _sense_prefix(func)
    state = "ON" if enabled else "OFF"
    await _get_conn().write(f"{prefix}:RANGe:AUTO {state}")
    return f"Autorange {'enabled' if enabled else 'disabled'} for {FUNCTIONS.get(func, func)}"


# ---------------------------------------------------------------------------
# Trigger & Sampling
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_trigger(
    source: str = "IMM",
    delay: Optional[float] = None,
    count: Optional[int] = None,
) -> str:
    """Configure the trigger system.

    Args:
        source: Trigger source — "IMM" (immediate/continuous), "BUS" (software trigger),
            or "EXT" (external rear-panel input).
        delay: Trigger delay in seconds. Omit to leave unchanged.
        count: Number of triggers to accept. Omit to leave unchanged.
    """
    source_map = {"IMM": "IMMediate", "BUS": "BUS", "EXT": "EXTernal"}
    src = source.upper()
    scpi_src = source_map.get(src, src)
    c = _get_conn()
    await c.write(f"TRIGger:SOURce {scpi_src}")
    parts = [f"Trigger source={src}"]
    if delay is not None:
        await c.write(f"TRIGger:DELay {delay}")
        parts.append(f"delay={delay}s")
    if count is not None:
        await c.write(f"TRIGger:COUNt {count}")
        parts.append(f"count={count}")
    return ", ".join(parts)


@mcp.tool()
async def set_sample_count(count: int = 1) -> str:
    """Set the number of samples per trigger event.

    Total readings = sample_count x trigger_count.

    Args:
        count: Number of samples per trigger (1 to instrument max).
    """
    await _get_conn().write(f"SAMPle:COUNt {count}")
    return f"Sample count set to {count}"


# ---------------------------------------------------------------------------
# Monitor — fixed-duration repeated measurements
# ---------------------------------------------------------------------------


@mcp.tool()
async def monitor(
    function: str = "VOLT:DC",
    interval_ms: int = 1000,
    duration_s: float = 10.0,
    range: Optional[str] = None,
) -> str:
    """Continuously measure for a fixed duration, returning a time-series of readings.

    Configures the instrument then takes repeated readings at the specified interval.

    Args:
        function: Measurement function (e.g. "VOLT:DC", "RES", "CURR:AC").
        interval_ms: Time between readings in milliseconds (minimum ~200ms practical).
        duration_s: Total monitoring duration in seconds (max 300).
        range: Measurement range. Omit for auto.

    Returns:
        JSON with channel config and array of {time, value} readings.
    """
    if duration_s > 300:
        return "Error: duration_s cannot exceed 300 seconds"

    func = _normalize_function(function)
    scpi_func = _scpi_func_for_configure(func)

    # Configure
    cmd = f"CONFigure:{scpi_func}"
    if range is not None:
        cmd += f" {range}"
    c = _get_conn()
    await c.write(cmd)

    interval = interval_ms / 1000.0
    data = []
    start_time = time.time()

    while time.time() - start_time < duration_s:
        t0 = asyncio.get_event_loop().time()
        try:
            val = await c.query("READ?")
            data.append({
                "time": round(time.time() - start_time, 3),
                "value": val,
            })
        except Exception as e:
            data.append({
                "time": round(time.time() - start_time, 3),
                "error": str(e),
            })
        elapsed = asyncio.get_event_loop().time() - t0
        await asyncio.sleep(max(0, interval - elapsed))

    return json.dumps({
        "function": FUNCTIONS.get(func, func),
        "samples": len(data),
        "duration_s": round(time.time() - start_time, 3),
        "readings": data,
    })


# ---------------------------------------------------------------------------
# Raw SCPI escape hatch
# ---------------------------------------------------------------------------


@mcp.tool()
async def scpi_command(command: str, is_query: bool = True) -> str:
    """Send an arbitrary SCPI command to the instrument.

    Use this for commands not covered by other tools. For the full SCPI command
    reference, consult the Siglent SDM Programming Guide.

    Args:
        command: The SCPI command string (e.g. "*IDN?", "SENS:VOLT:DC:NPLC 10").
        is_query: True if a response is expected (command ends with ?), False for write-only.

    Returns:
        The instrument response for queries, or confirmation for writes.
    """
    if is_query:
        return await _get_conn().query(command)
    await _get_conn().write(command)
    return f"Sent: {command}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
