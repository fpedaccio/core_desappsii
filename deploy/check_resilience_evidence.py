"""Verify saved local resilience evidence; does not execute outages."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8-sig"))


def unchanged(report):
    before, after = report["before"], report["after"]
    for suffix in ("-api-1", "-worker-1"):
        names = [name for name in before if name.endswith(suffix)]
        require(len(names) == 1, "Missing or ambiguous application container")
        name = names[0]
        require(before[name] == after[name], "Application container changed")
        require(after[name]["status"] == "running", "Application not running")
    names = [name for name in before if name.endswith("-rabbitmq-1")]
    require(len(names) == 1, "Missing broker container")
    name = names[0]
    require(before[name]["id"] == after[name]["id"], "Broker was replaced")
    require(before[name]["started_at"] != after[name]["started_at"],
            "No broker restart evidenced")
    require(after[name]["status"] == "running", "Broker not running")
    require(report["broker_stopped"] is True, "Broker stop not confirmed")


def verify(folder):
    reconnect = read(folder, "reconexion.json")
    unchanged(reconnect)
    require(reconnect["consumers_recovered"] is True, "Consumers not recovered")
    require(reconnect["outage_seconds"] >= 15, "Unexpected outage duration")

    files = list(folder.glob("persistencia-*.json"))
    require(len(files) == 1, "Expected exactly one persistence report")
    persistence = read(folder, files[0].name)
    unchanged(persistence)
    for key in ("publication_confirmed", "message_preserved", "test_queue_removed"):
        require(persistence[key] is True, "Persistence check failed: " + key)

    outage = read(folder, "http-durante-caida.json")
    recovery = read(folder, "http-recuperacion.json")
    differences = read(folder, "http-diferencias.json")
    duplicate = read(folder, "http-deduplicacion.json")
    event_id = outage["event_id"]
    require(all(item["event_id"] == event_id for item in
                (recovery, differences, duplicate)), "Mismatched event identifiers")
    require(outage["queue"] == recovery["queue"], "Mismatched destination")
    require(outage["broker_stopped"] is True, "HTTP outage not confirmed")
    require(outage["broker_start_command_succeeded"] is True, "Broker start failed")
    require(outage["publication"]["http_status"] == 202, "HTTP event not accepted")
    require(outage["publication"]["transport_error"] is None, "HTTP transport failed")
    require(recovery["event_count"] == 1, "Event missing or duplicated")
    require(recovery["message_found"] is True, "Recovered message missing")
    require(recovery["message_id_matches"] is True, "Message ID changed")
    require(recovery["queued_messages_before_read"] == 1, "Unexpected queue count")
    rows = recovery["deliveries"]
    require(len(rows) == 1, "Unexpected delivery count")
    require(rows[0]["status"] == "DELIVERED", "Delivery not published")
    require(rows[0]["attempts"] >= 2, "No deferred delivery attempt evidenced")
    require(rows[0]["queue"] == recovery["queue"], "Wrong delivery queue")
    require(differences["data_matches"] is True, "Event data changed")
    changes = differences["differences"]
    require(len(changes) == 1 and changes[0]["field"] == "occurredAt",
            "Unexpected envelope differences")
    change = changes[0]
    require(change["present_in_sent"] is True and change["present_in_received"] is True,
            "Timestamp missing")
    sent = datetime.fromisoformat(change["sent"].replace("Z", "+00:00"))
    received = datetime.fromisoformat(change["received"].replace("Z", "+00:00"))
    require(sent.utcoffset() is not None and received.utcoffset() is not None,
            "Timezone missing")
    require(sent == received, "Timestamp instant changed")

    require(duplicate["http_status"] == 200 and duplicate["duplicate"] is True,
            "Duplicate not acknowledged")
    require(duplicate["before"] == duplicate["after"], "Duplicate changed delivery state")
    snapshot = duplicate["after"]
    require(snapshot["event_count"] == 1 and snapshot["queued_messages"] == 1,
            "Duplicate changed event or message count")
    require(snapshot["consumers"] == 0, "Consumer could hide duplicate messages")
    require(len(snapshot["deliveries"]) == 1, "Duplicate delivery count")
    require(snapshot["deliveries"][0]["status"] == rows[0]["status"]
            and snapshot["deliveries"][0]["attempts"] == rows[0]["attempts"],
            "Recovery and deduplication delivery state differs")

    cleanup = read(folder, "limpieza.json")
    for key in ("module_deactivated", "subscription_deactivated",
                "synthetic_credential_removed", "test_message_and_queue_removed",
                "temporary_credential_file_removed", "event_and_delivery_preserved"):
        require(cleanup[key] is True, "Incomplete cleanup: " + key)
    return event_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    try:
        event_id = verify(args.folder)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, "Evidence validation failed: " + str(error) + "\n")
    print("PASS: saved evidence is consistent for four local resilience scenarios")
    print("HTTP event:", event_id)
    print("This command validates reports; it does not rerun outages or prove processing by a module.")


if __name__ == "__main__":
    main()
