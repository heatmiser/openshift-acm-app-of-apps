#!/usr/bin/env python3
"""FastAPI node registration listener for the ACM cluster onboarding pipeline.

Nodes boot from the hardware discovery live ISO and POST their hardware and
network facts to this listener. Ansible drains registrations one at a time
via the /drain long-poll endpoint, processing each node as it arrives rather
than waiting for all nodes to complete.

Usage (invoked by start_registration_listener.yml):
    uvicorn registration_listener:app --host 0.0.0.0 --port 8080

Endpoints:
    POST /register     Node callback — adds registration to the queue
    GET  /drain        Long-poll — returns one registration or null on timeout
    GET  /status       Queue depth — how many registrations are waiting
    GET  /healthz      Liveness check
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="ACM Node Registration Listener", version="1.0.0")

# One queue per listener process — all registrations flow through here.
_queue: asyncio.Queue[dict] = asyncio.Queue()


class NodeRegistration(BaseModel):
    """Payload sent by each node on live ISO boot."""

    serial: str      # chassis serial number (dmidecode -t1 / Redfish)
    ip: str          # primary IPv4 address the node acquired on boot
    mac: str         # MAC address of the primary interface
    interface: str   # OS interface name (e.g. eno1, eth0, bond0)
    hostname: str = ""  # short hostname if set by the live ISO


@app.post("/register", status_code=202)
async def register(node: NodeRegistration) -> dict:
    """Receive a node registration callback from the live ISO.

    Called by each node after it boots and discovers its own hardware facts.
    The payload is queued for Ansible to drain via GET /drain.
    """
    log.info(
        "Registered: serial=%s ip=%s mac=%s interface=%s",
        node.serial,
        node.ip,
        node.mac,
        node.interface,
    )
    await _queue.put(node.model_dump())
    return {"status": "queued", "serial": node.serial, "queue_depth": _queue.qsize()}


@app.get("/drain")
async def drain(timeout: int = 30) -> Optional[dict]:
    """Long-poll: return the next registration or null on timeout.

    Ansible calls this endpoint in a loop, receiving one node registration per
    call. The endpoint blocks for up to `timeout` seconds before returning null
    so that Ansible does not busy-poll the queue.

    Args:
        timeout: Seconds to block waiting for a registration (default: 30).
                 Set via the cluster_onboard_node_poll_timeout variable.
    """
    try:
        node = await asyncio.wait_for(_queue.get(), timeout=float(timeout))
        _queue.task_done()
        log.info("Drained: serial=%s ip=%s", node.get("serial"), node.get("ip"))
        return node
    except asyncio.TimeoutError:
        return None


@app.get("/status")
async def status() -> dict:
    """Return the number of registrations currently waiting in the queue."""
    return {"pending": _queue.qsize()}


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness check used by start_registration_listener.yml to confirm startup."""
    return {"status": "ok"}
