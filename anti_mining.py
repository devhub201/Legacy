import time
import threading

import database as db
import docker_manager as dm

MINER_SIGNATURES = [
    "xmrig", "xmr-stak", "xmrstak", "cpuminer", "minerd", "ccminer",
    "cgminer", "bfgminer", "ethminer", "phoenixminer", "t-rex", "trex",
    "gminer", "lolminer", "nbminer", "teamredminer", "srbminer",
    "srbminer-multi", "nanominer", "wildrig", "cast_xmr", "excavator",
    "claymore", "nheqminer", "z-enemy", "bminer",
]


def _scan_container(node, container):
    try:
        top = container.top()
        titles = top.get("Titles", [])
        cmd_idx = titles.index("CMD") if "CMD" in titles else len(titles) - 1
        for proc in top.get("Processes", []):
            cmdline = " ".join(proc).lower()
            for sig in MINER_SIGNATURES:
                if sig in cmdline:
                    return sig
    except Exception as e:
        print(f"[anti-mining] scan error on {container.name}: {e}")
    return None


def _handle_violation(node, container_name, signature):
    vps = db.get_vps_by_container(container_name)
    if not vps:
        return
    print(f"[anti-mining] MINING DETECTED: {container_name} ({signature}) — suspending")
    try:
        dm.stop_container(node, container_name)
    except Exception as e:
        print(f"[anti-mining] failed to stop {container_name}: {e}")
    db.set_vps_status(vps["id"], "suspended", reason=f"Crypto mining detected ({signature})")
    db.queue_violation(vps["id"], signature)


def _scan_node(node):
    try:
        client = dm.get_client(node)
        containers = client.containers.list(filters={"label": "legacycloud=vps"})
        for container in containers:
            sig = _scan_container(node, container)
            if sig:
                _handle_violation(node, container.name, sig)
    except Exception as e:
        print(f"[anti-mining] node scan error ({node.get('name')}): {e}")


def _monitor_loop():
    while True:
        for node in db.list_nodes():
            _scan_node(node)
        time.sleep(60)


def start_monitor():
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    print("[anti-mining] monitor started (scanning every 60s)")
