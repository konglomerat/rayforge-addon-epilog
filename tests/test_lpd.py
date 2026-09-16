import asyncio
from contextlib import asynccontextmanager

import pytest

from epilog_zing.lpd import EpilogLpdClient, LpdError


@asynccontextmanager
async def printer(handler):
    tasks = set()

    async def connection(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            await handler(reader, writer)
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield EpilogLpdClient("127.0.0.1", port, timeout=1)
    finally:
        server.close()
        await server.wait_closed()
        remaining = list(tasks)
        for task in remaining:
            task.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)


@pytest.mark.asyncio
async def test_complete_epilog_exchange():
    received = asyncio.get_running_loop().create_future()
    payload = b"PJL-test-payload" + bytes(4096)

    async def receive(reader, writer):
        try:
            assert await reader.readline() == b"\x02\n"
            writer.write(b"\x00")
            control_header = await reader.readline()
            assert control_header.startswith(b"\x02")
            size, control_name = control_header[1:].strip().split(b" ")
            assert control_name.startswith(b"cfA")
            writer.write(b"\x00")
            control = await reader.readexactly(int(size))
            assert await reader.readexactly(1) == b"\x00"
            writer.write(b"\x00")
            data_header = await reader.readline()
            assert data_header.startswith(b"\x03")
            size, data_name = data_header[1:].strip().split(b" ")
            assert data_name == b"df" + control_name[2:]
            assert int(size) == len(payload)
            writer.write(b"\x00")
            data = await reader.readexactly(int(size))
            assert data == payload
            assert b"l" + data_name + b"\n" in control
            assert b"U" + data_name + b"\n" in control
            assert b"JJob___E\n" in control
            writer.write(b"\x00")
            await writer.drain()
            assert await reader.read() == b""
            received.set_result(True)
        except (
            AssertionError,
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
        ) as exc:
            received.set_exception(exc)

    async with printer(receive) as client:
        await client.upload(payload, "Job\r\n\x1bE")
        assert await asyncio.wait_for(received, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected_stage", range(5))
async def test_rejection_at_every_stage_closes_without_retry(rejected_stage):
    connections = 0
    closed = asyncio.Event()

    async def reject(reader, writer):
        nonlocal connections
        connections += 1
        size = 0
        for stage in range(5):
            if stage in (0, 1, 3):
                line = await reader.readline()
                if stage in (1, 3):
                    size = int(line[1:].split(b" ")[0])
            else:
                await reader.readexactly(size + (1 if stage == 2 else 0))
            writer.write(b"\x01" if stage == rejected_stage else b"\x00")
            await writer.drain()
            if stage == rejected_stage:
                assert await reader.read() == b""
                closed.set()
                return

    async with printer(reject) as client:
        with pytest.raises(LpdError, match="rejected"):
            await client.upload(b"payload", "test")
        await asyncio.wait_for(closed.wait(), 2)
    assert connections == 1


@pytest.mark.asyncio
async def test_missing_ack_times_out_and_closes():
    closed = asyncio.Event()

    async def silent(reader, writer):
        await reader.readline()
        assert await reader.read() == b""
        closed.set()

    async with printer(silent) as client:
        client.timeout = 0.05
        with pytest.raises(LpdError, match="timed out"):
            await client.upload(b"test", "test")
        await asyncio.wait_for(closed.wait(), 2)


@pytest.mark.asyncio
async def test_disconnect_is_not_success():
    async def disconnect(reader, writer):
        await reader.readline()

    async with printer(disconnect) as client:
        with pytest.raises(LpdError, match="disconnected"):
            await client.upload(b"test", "test")


@pytest.mark.asyncio
async def test_cancel_closes_connection():
    waiting = asyncio.Event()
    closed = asyncio.Event()

    async def silent(reader, writer):
        await reader.readline()
        waiting.set()
        assert await reader.read() == b""
        closed.set()

    async with printer(silent) as client:
        task = asyncio.create_task(client.upload(b"test", "test"))
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closed.wait(), 2)


@pytest.mark.asyncio
async def test_probe_does_not_submit_a_job():
    received = asyncio.get_running_loop().create_future()

    async def record(reader, writer):
        received.set_result(await reader.read())

    async with printer(record) as client:
        await client.probe()
        assert await asyncio.wait_for(received, 2) == b""
