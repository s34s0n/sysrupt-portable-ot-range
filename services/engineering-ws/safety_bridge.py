"""Safety Bridge - TCP proxy from 0.0.0.0:10102 to 10.0.5.201:102.

This simulates a forgotten maintenance bridge left on the Engineering
Workstation during commissioning. It allows an attacker who has
compromised the EWS to reach the safety PLC via S7comm.
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [safety-bridge] %(levelname)s: %(message)s",
)
log = logging.getLogger("safety-bridge")

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 10102
TARGET_HOST = "10.0.5.201"
TARGET_PORT = 102


async def relay(reader, writer, label):
    """Copy bytes from reader to writer until EOF."""
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        writer.close()


async def handle_client(client_reader, client_writer):
    peer = client_writer.get_extra_info("peername")
    log.info("connection from %s", peer)
    try:
        target_reader, target_writer = await asyncio.wait_for(
            asyncio.open_connection(TARGET_HOST, TARGET_PORT),
            timeout=5.0,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        log.warning("cannot reach %s:%d - %s", TARGET_HOST, TARGET_PORT, exc)
        client_writer.close()
        return

    log.info("connected to %s:%d", TARGET_HOST, TARGET_PORT)
    await asyncio.gather(
        relay(client_reader, target_writer, "client->target"),
        relay(target_reader, client_writer, "target->client"),
    )
    log.info("session closed for %s", peer)


async def main():
    server = await asyncio.start_server(
        handle_client, LISTEN_HOST, LISTEN_PORT,
    )
    addr = server.sockets[0].getsockname()
    log.info("listening on %s:%d -> %s:%d", addr[0], addr[1], TARGET_HOST, TARGET_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("stopped")
