"""The Epilog variant of the LPD receive-job exchange on TCP port 515."""

import asyncio
import secrets

from .encoder import job_name


class LpdError(ConnectionError):
    """The printer rejected, interrupted, or failed to acknowledge a job."""


class EpilogLpdClient:
    """Open a fresh connection per upload; never retry a partial job."""

    def __init__(self, host: str, port: int = 515, timeout: float = 30):
        self.host = host
        self.port = port
        self.timeout = timeout

    async def _open(self):
        return await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout
        )

    async def _close(self, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), self.timeout)
        except OSError, TimeoutError:
            pass

    async def probe(self) -> None:
        """Check TCP reachability without issuing a print command."""
        _, writer = await self._open()
        await self._close(writer)

    async def upload(self, payload: bytes, title: str) -> None:
        if not payload:
            raise ValueError("Cannot upload an empty Epilog job")
        reader, writer = await self._open()
        try:
            await self._transfer(reader, writer, payload, job_name(title))
        finally:
            await self._close(writer)

    async def _transfer(self, reader, writer, payload: bytes, title: str):
        suffix = f"A{secrets.randbelow(1000):03d}rayforge"
        data_name = f"df{suffix}"
        control_name = f"cf{suffix}"
        control = (
            f"Hrayforge\nPrayforge\nJ{title}\n"
            f"l{data_name}\nU{data_name}\nN{title}\n"
        ).encode("ascii")
        stages = (
            (b"\x02\n", "receive job"),
            (
                f"\x02{len(control)} {control_name}\n".encode("ascii"),
                "control file header",
            ),
            (control + b"\x00", "control file"),
            (
                f"\x03{len(payload)} {data_name}\n".encode("ascii"),
                "data file header",
            ),
            (payload, "data file"),
        )
        for data, stage in stages:
            for offset in range(0, len(data), 65536):
                writer.write(data[offset : offset + 65536])
                await asyncio.wait_for(writer.drain(), self.timeout)
            await self._ack(reader, stage)

    async def _ack(self, reader: asyncio.StreamReader, stage: str) -> None:
        try:
            response = await asyncio.wait_for(
                reader.readexactly(1), self.timeout
            )
        except TimeoutError as exc:
            raise LpdError(f"Epilog timed out acknowledging {stage}") from exc
        except asyncio.IncompleteReadError as exc:
            raise LpdError(f"Epilog disconnected during {stage}") from exc
        if response != b"\x00":
            raise LpdError(f"Epilog rejected {stage} (code {response[0]})")
