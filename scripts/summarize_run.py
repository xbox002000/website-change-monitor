"""Summarize the last local run: dataset items and simulated PPE charges."""
import collections
import glob
import json


def load(pattern):
    return [json.load(open(f)) for f in sorted(glob.glob(pattern)) if not f.endswith("__metadata__.json")]


items = load("storage/datasets/default/*.json")
print(f"{len(items)} dataset item(s)")
by = collections.Counter()
for i in items:
    if i.get("errorClass"):
        by["error"] += 1
    elif i.get("changed"):
        by["changed"] += 1
    elif i.get("isFirstSeen"):
        by["first"] += 1
    else:
        by["unchanged"] += 1
print("  by outcome:", dict(by))
prices = {k: v["eventPriceUsd"] for k, v in json.load(open(".actor/pay_per_event.json")).items()}
counts = collections.Counter()
for e in load("storage/datasets/charging-log/*.json"):
    counts[e["event_name"]] += e["charged_count"]
total = 0.0
for k, n in counts.items():
    if k not in prices:
        print(f"  (simulated at $0) {k}: {n} x  <- keep apify-default-dataset-item REMOVED from the live pricing")
        continue
    total += n * prices[k]
    print(f"  charge {k}: {n} x ${prices[k]} = ${n * prices[k]:.5f}")
print(f"  TOTAL simulated custom-event charge: ${total:.5f}")
