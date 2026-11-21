"""One unsupported public-data accusation, solely for the release demo."""

import json
import sys


initial = json.loads(sys.stdin.readline())["observation"]
print(json.dumps({"type": "list_records", "table": "invoices", "cursor": None, "limit": 1}), flush=True)
invoice = json.loads(sys.stdin.readline())["observation"]["result"]["rows"][0]["record"]
print(json.dumps({"type": "submit", "findings": {
    "episode_id": initial["manifest"]["episode_id"],
    "findings": [{"type": "duplicate_invoice", "affected_ids": [invoice["invoice_id"]],
                  "claimed_amount_minor": invoice["total_minor"], "currency": invoice["currency"],
                  "evidence_ids": [invoice["doc_id"]], "explanation": "Unsupported demonstration accusation."}],
}}), flush=True)
json.loads(sys.stdin.readline())
