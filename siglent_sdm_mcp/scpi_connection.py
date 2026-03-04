import asyncio


class SCPIConnection:
    """Async TCP connection to a SCPI instrument.

    Handles the Siglent SDM welcome banner that is sent on connect:
        Welcome to the SCPI instrument 'Siglent SDM3045X'
        >>
    """

    def __init__(self, host: str, port: int = 5024, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        # Drain the welcome banner (reads until we see ">>" prompt)
        await self._drain_banner()

    async def _drain_banner(self):
        """Read and discard the welcome banner sent on connection."""
        try:
            while True:
                line = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=1.0,
                )
                text = line.decode("ascii", errors="replace").strip()
                if text.startswith(">>") or not text:
                    break
        except asyncio.TimeoutError:
            pass  # No more banner data

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def _ensure_connected(self):
        if self._writer is None or self._writer.is_closing():
            await self.connect()

    async def query(self, command: str) -> str:
        """Send a command and return the response (strips trailing whitespace)."""
        async with self._lock:
            await self._ensure_connected()
            self._writer.write(f"{command}\n".encode("ascii"))
            await self._writer.drain()
            try:
                response = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=self.timeout,
                )
                return response.decode("ascii").strip()
            except asyncio.TimeoutError:
                await self.disconnect()
                raise

    async def write(self, command: str):
        """Send a command with no response expected."""
        async with self._lock:
            await self._ensure_connected()
            self._writer.write(f"{command}\n".encode("ascii"))
            await self._writer.drain()
            await asyncio.sleep(0.1)

    async def read_binary(self, command: str) -> bytes:
        """Send a command and return binary response (for screenshots etc.)."""
        async with self._lock:
            await self._ensure_connected()
            self._writer.write(f"{command}\n".encode("ascii"))
            await self._writer.drain()
            try:
                # Read IEEE 488.2 definite length block: #<n><length><data>
                header = await asyncio.wait_for(
                    self._reader.readexactly(1),
                    timeout=self.timeout,
                )
                if header != b"#":
                    # Not a binary block, read as text
                    rest = await self._reader.readline()
                    return header + rest
                n_digits_byte = await self._reader.readexactly(1)
                n_digits = int(n_digits_byte.decode("ascii"))
                length_bytes = await self._reader.readexactly(n_digits)
                length = int(length_bytes.decode("ascii"))
                data = await asyncio.wait_for(
                    self._reader.readexactly(length),
                    timeout=self.timeout,
                )
                # Read trailing newline
                await self._reader.readline()
                return data
            except asyncio.TimeoutError:
                await self.disconnect()
                raise
