"""Stage 05 transport demo: derive one allocation claim from public tools only.

This deliberately tiny policy handles the hand-authored fixture, not generated
companies. Stage 09 supplies the general reconciliation baseline.
"""

import json
import sys


def receive():
    return json.loads(sys.stdin.readline())


def act(action):
    print(json.dumps(action), flush=True)
    return receive()["observation"]["result"]


initial = receive()["observation"]
page = act({"type": "list_records", "table": "payments", "cursor": None, "limit": 50})
payment_id = page["rows"][0]["id"]
record = act({"type": "get_record", "table": "payments", "id": payment_id})
document = act({"type": "get_document", "doc_id": record["record"]["doc_id"]})
payment, settlement = document["payment"], document["settlement"]
directive = payment["invoice_refs"][0]
applied = sum(item["applied_minor"] for item in settlement["allocations"] if item["invoice_id"] == directive["invoice_id"])
difference = int(act({"type": "calculator", "expression": f"{directive['amount_minor']} - {applied}"}))
findings = []
if difference:
    findings.append({
        "type": "payment_allocation", "affected_ids": [payment_id, directive["invoice_id"]],
        "claimed_amount_minor": abs(difference), "currency": "KZT",
        "evidence_ids": [payment["doc_id"], settlement["evidence_id"]],
        "explanation": "The directed payment exceeds its recorded application.",
    })
act({"type": "submit", "findings": {"episode_id": initial["manifest"]["episode_id"], "findings": findings}})
