# Website Change Monitor — Hash & Text Diff

**Watch a list of URLs for content changes — SHA-256 hash, optional CSS selector, and a `difflib` text diff. No browser. No paid LLM.**
Paste URLs, or chain from Sitemap URL Discovery / URL Status Checker datasets. Snapshots persist in a named (or ID) key-value store so scheduled runs can compare against the last check. Default memory: **256 MB**. Failed network checks are free by default.

## What you get

- 🔐 **Content hash** — SHA-256 of normalized page text (script/style stripped)
- 🧩 **Optional CSS selector** — hash only `main` / `article` / `#content`
- 📝 **Text diff** — stdlib `difflib` unified diff + lines added/removed (no LLM “explanation”)
- 🧺 **Persistent snapshots** — named KV store (or explicit store ID) across runs
- 🔌 **Chain-friendly** — same `{ "url": ... }` shape as Sitemap / URL-status outputs
- 💸 **PPE** — low start + per successful check + extra only when hash changes; failures free by default
- 💾 **Light** — HTTP GET only, target ≤512 MB

## Measured results

Local + private cloud benches (2026-10-02 Asia/Taipei). PPE locked after cloud margin benches — see **Measured results** above.

| Test | Result |
|---|---|
| Local smoke (2 URLs, first / second / forced-change) | first×2 → unchanged×2 → changed×1 + `page-changed` charge; peak **78 MB** |
| Local errors (1 ok + 1 bad DNS) | charged **1** check only (fail free); peak **78 MB** |
| Cloud smoke `rK92EHmHttVUrjPhY` / `dncJ8mOaNHB5OgzUh` (2 URLs, 256 MB, build **0.1.2**) | **SUCCEEDED**; peak **86 MB**; settled **~$0.00037** |
| Cloud fail-free `ZOyhRn1x65VdFG73d` | check×1 charged; settled **$0.000120** |
| Cloud bench `P89Kp73Zbw8wYUv6e` (5 URLs) | peak **88 MB**; settled **$0.000492** (~$0.000098 / URL) |
| Cloud changed `h7LQ6fUdvbnNWOTl0` | check×2 + changed×1; peak **84 MB**; settled **$0.000341** |

## Use cases

- **Scheduled content watch** on a sitemap-derived URL list
- **Competitor / pricing page** change alerts (hash + diff, not marketing AI)
- **Re-crawl trigger** — only re-run doc/enrichment Actors when `changed=true`
- **Post-hygiene monitor** after URL Status Checker

## How to use

1. Add URLs, and/or a **Source dataset ID** from Sitemap / URL-status.
2. Set a **Snapshot store name** (or ID) you will reuse on every schedule.
3. Optional: CSS selector, ignore regexes, output filter `changed`.
4. Click **Start**. Dataset + `SUMMARY` / `OUTPUT` in the run KV; snapshots in the snapshot store.

### Input example

```json
{
  "urls": [
    { "url": "https://example.com/" },
    { "url": "https://example.org/" }
  ],
  "snapshotStoreName": "website-change-snapshots",
  "storePreviousText": true,
  "maxUrls": 100,
  "outputFilter": "all"
}
```

Chain from Sitemap / URL-status:

```json
{
  "datasetId": "<upstream-run-default-dataset-id>",
  "snapshotStoreName": "my-site-watch",
  "cssSelector": "main",
  "outputFilter": "changed"
}
```

### Output example (one dataset item)

```json
{
  "url": "https://example.com/",
  "finalUrl": "https://example.com/",
  "httpStatus": 200,
  "ok": true,
  "contentHash": "b94d27b9…",
  "previousHash": "a3f1…",
  "changed": true,
  "isFirstSeen": false,
  "diffSummary": {
    "isFirstSeen": false,
    "linesAdded": 2,
    "linesRemoved": 1,
    "unifiedDiff": "--- previous\n+++ current\n@@ …",
    "truncated": false
  },
  "checkedAt": "2026-10-02T01:00:00+00:00",
  "errorClass": null
}
```

### Key-value store records (run)

| Key | Content |
|---|---|
| `SUMMARY` | Counts: totalChecked, changed, firstSeen, failed, charged, peakMemoryMb |
| `OUTPUT` | Same summary |

Snapshots are written to the **snapshot** store (not the run default KV), keyed as `snap_<sha256(url)>`.

## Pricing

Pay per event (locked from measured cloud cost — see **Measured results** above):

| Event | Price |
|---|---|
| Actor start (Apify synthetic) | **$0.001** / GB (1 GB min) |
| Page checked (primary) | **$0.0015** per successful fetch+hash |
| Page changed | **$0.008** when hash differs from previous snapshot |

Failed checks (DNS / timeout / network) are **not charged** unless you enable `chargeFailedChecks`. First-seen pages charge `page-checked` only (not `page-changed`).

## Chaining

```
Sitemap URL Discovery → URL Status Checker → Website Change Monitor
                                              └─ on changed → re-run doc/enrichment
```

## Limits

- HTTP only — no headless browser / JS rendering (keeps memory and CU low).
- Dynamic pages that inject clocks/CSRF into the main text may need `ignorePatterns` or a tighter `cssSelector`.
- Very large HTML is truncated at `maxBodyBytes` (default 2 MB).

## License & source code

This Actor is open source under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see `LICENSE`. Runtime stack: `httpx` (BSD-3-Clause), `selectolax` (MIT), Apify SDK (Apache-2.0).
