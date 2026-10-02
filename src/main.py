"""Apify Actor: website change monitor (content hash + text diff).

Accepts a URL list and/or another Actor's dataset / KV record (Sitemap / URL-status
outputs). Fetches each URL over HTTP, extracts text (optional CSS selector), hashes
with SHA-256, compares to a persistent KV snapshot, and emits changed + difflib
summary. No browser, no paid LLM. Failed checks free by default.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import resource
import time
from collections import Counter

import httpx
from apify import Actor

from charging import Charger
from inputs import collect_urls, merge_unique, normalize_url, urls_from_payload
from monitor import check_url
from extract import snapshot_key

EVENT_CHECK = "page-checked"
EVENT_CHANGED = "page-changed"
UA = "Mozilla/5.0 (compatible; WebsiteChangeMonitor/0.1; +https://apify.com)"
PUSH_BATCH = 50


async def load_from_dataset(dataset_id: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    raw: list[str] = []
    try:
        ds = await Actor.open_dataset(id=dataset_id)
        async for item in ds.iterate_items():
            if isinstance(item, dict) and item.get("url"):
                raw.append(str(item["url"]))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Could not read dataset {dataset_id}: {e}")
        return [], warnings
    out: list[str] = []
    seen: set[str] = set()
    for r in raw:
        u = normalize_url(r)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
        elif u is None:
            warnings.append(f"Ignored invalid URL from dataset: {r[:200]}")
    return out, warnings


async def load_from_kv(store_id: str, record_key: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    try:
        store = await Actor.open_key_value_store(id=store_id)
        rec = await store.get_value(record_key)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Could not read KV {store_id}/{record_key}: {e}")
        return [], warnings
    if rec is None:
        warnings.append(f"KV record {record_key} not found in store {store_id}")
        return [], warnings
    raw = urls_from_payload(rec)
    out: list[str] = []
    seen: set[str] = set()
    for r in raw:
        u = normalize_url(r)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    if not out:
        warnings.append(f"No URLs found in KV record {record_key}")
    return out, warnings


async def open_snapshot_store(inp: dict):
    """Persistent KV for previous hashes/text. Prefer explicit id, else named store."""
    sid = inp.get("snapshotStoreId")
    if sid:
        return await Actor.open_key_value_store(id=str(sid))
    name = (inp.get("snapshotStoreName") or "website-change-snapshots").strip() or "website-change-snapshots"
    return await Actor.open_key_value_store(name=name)


async def main() -> None:
    async with Actor:
        t0 = time.time()
        inp = await Actor.get_input() or {}
        charger = Charger(EVENT_CHECK)
        charge_failed = bool(inp.get("chargeFailedChecks", False))
        css_selector = (inp.get("cssSelector") or "").strip() or None
        ignore_patterns = [p for p in (inp.get("ignorePatterns") or []) if isinstance(p, str) and p]
        store_text = bool(inp.get("storePreviousText", True))
        max_body = max(10_000, min(int(inp.get("maxBodyBytes", 2_000_000) or 2_000_000), 10_000_000))
        max_diff = max(5, min(int(inp.get("maxDiffLines", 40) or 40), 200))
        max_stored = max(0, min(int(inp.get("maxStoredTextChars", 100_000) or 100_000), 500_000))
        out_filter = inp.get("outputFilter", "all") or "all"
        timeout = float(inp.get("requestTimeoutSecs", 30))
        conc = max(1, min(int(inp.get("maxConcurrency", 5)), 20))
        checked_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

        proxy_url = None
        if (inp.get("proxyConfiguration") or {}).get("useApifyProxy") or (
            inp.get("proxyConfiguration") or {}
        ).get("proxyUrls"):
            pc = await Actor.create_proxy_configuration(actor_proxy_input=inp["proxyConfiguration"])
            proxy_url = await pc.new_url() if pc else None

        headers = {"User-Agent": inp.get("userAgent") or UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
        limits = httpx.Limits(max_connections=conc * 2, max_keepalive_connections=conc)

        snap_store = await open_snapshot_store(inp)
        Actor.log.info(f"Snapshot store ready (storePreviousText={store_text})")

        async with httpx.AsyncClient(
            headers=headers, limits=limits, proxy=proxy_url, http2=False, follow_redirects=True
        ) as client:
            urls, warns = await collect_urls(inp.get("urls"), client=client)
            for w in warns:
                Actor.log.warning(w)

            if inp.get("datasetId"):
                extra, w2 = await load_from_dataset(str(inp["datasetId"]))
                for w in w2:
                    Actor.log.warning(w)
                urls = merge_unique(urls, extra)
                Actor.log.info(f"Loaded {len(extra)} URL(s) from dataset {inp['datasetId']}")

            if inp.get("keyValueStoreId"):
                key = inp.get("keyValueRecordKey") or "DOC_TO_MARKDOWN_INPUT"
                extra, w3 = await load_from_kv(str(inp["keyValueStoreId"]), str(key))
                for w in w3:
                    Actor.log.warning(w)
                urls = merge_unique(urls, extra)
                Actor.log.info(f"Loaded {len(extra)} URL(s) from KV {inp['keyValueStoreId']}/{key}")

            if not urls:
                raise ValueError(
                    "Provide at least one URL in `urls`, or a `datasetId` / `keyValueStoreId` from another Actor."
                )

            max_urls = int(inp.get("maxUrls", 500) or 0) or None
            budget = charger.budget(EVENT_CHECK)
            if budget is not None and (max_urls is None or budget < max_urls):
                Actor.log.info(f"Spending limit allows about {budget} check(s); capping maxUrls.")
                max_urls = budget
            if max_urls is not None:
                urls = urls[:max_urls]

            sem = asyncio.Semaphore(conc)
            checked = saved = ok_n = fail_n = changed_n = first_n = 0
            lock = asyncio.Lock()
            pending: list[dict] = []
            class_counts: Counter = Counter()

            async def flush(force: bool = False) -> None:
                nonlocal saved, pending
                if not pending:
                    return
                if not force and len(pending) < PUSH_BATCH:
                    return
                batch = pending
                pending = []
                success = [i for i in batch if i.get("_charge_check")]
                failed_rows = [i for i in batch if not i.get("_charge_check")]
                changed_flags = [bool(i.get("changed")) for i in success]
                for i in batch:
                    i.pop("_charge_check", None)
                    i.pop("_charge_changed", None)
                if success:
                    n = await charger.push_and_charge(success, EVENT_CHECK)
                    saved += n
                    changed_count = sum(1 for flag in changed_flags[:n] if flag)
                    if changed_count:
                        await charger.charge(EVENT_CHANGED, count=changed_count)
                    if n < len(success):
                        charger.limit_reached = True
                if failed_rows:
                    if charge_failed:
                        n2 = await charger.push_and_charge(failed_rows, EVENT_CHECK)
                        saved += n2
                    else:
                        await charger.push_free(failed_rows)
                        saved += len(failed_rows)

            def passes(item: dict) -> bool:
                if out_filter == "all":
                    return True
                if out_filter == "changed":
                    return bool(item.get("changed"))
                if out_filter == "changed_or_first":
                    return bool(item.get("changed") or item.get("isFirstSeen"))
                if out_filter == "errors":
                    return item.get("errorClass") is not None
                return True

            async def one(url: str) -> None:
                nonlocal checked, ok_n, fail_n, changed_n, first_n
                if charger.limit_reached:
                    return
                async with sem:
                    if charger.limit_reached:
                        return
                    key = snapshot_key(url)
                    try:
                        previous = await snap_store.get_value(key)
                    except Exception as e:  # noqa: BLE001
                        Actor.log.warning(f"Snapshot read failed for {url}: {e}")
                        previous = None
                    res = await check_url(
                        url,
                        client,
                        previous=previous if isinstance(previous, dict) else None,
                        css_selector=css_selector,
                        ignore_patterns=ignore_patterns,
                        max_body_bytes=max_body,
                        timeout=timeout,
                        store_text=store_text,
                        max_diff_lines=max_diff,
                        max_stored_text_chars=max_stored,
                    )
                    item = res.item
                    item["checkedAt"] = checked_at
                    item["_charge_check"] = res.ok
                    item["_charge_changed"] = res.changed

                    if res.ok:
                        snap_val = {
                            "url": url,
                            "contentHash": item["contentHash"],
                            "httpStatus": item["httpStatus"],
                            "checkedAt": checked_at,
                            "textChars": item["textChars"],
                        }
                        if res.text_for_store is not None:
                            snap_val["text"] = res.text_for_store
                        try:
                            await snap_store.set_value(key, snap_val)
                        except Exception as e:  # noqa: BLE001
                            Actor.log.warning(f"Snapshot write failed for {url}: {e}")

                async with lock:
                    checked += 1
                    if res.ok:
                        ok_n += 1
                        class_counts["ok"] += 1
                    else:
                        fail_n += 1
                        class_counts[item.get("errorClass") or "error"] += 1
                    if res.changed:
                        changed_n += 1
                    if item.get("isFirstSeen"):
                        first_n += 1
                    if passes(item):
                        pending.append(item)
                        await flush()
                    else:
                        # Still charge successful checks filtered out of dataset
                        if res.ok:
                            await charger.charge(EVENT_CHECK, count=1)
                            if res.changed:
                                await charger.charge(EVENT_CHANGED, count=1)
                        elif charge_failed:
                            await charger.charge(EVENT_CHECK, count=1)
                    if checked % 10 == 0 or checked == len(urls):
                        await Actor.set_status_message(
                            f"Checked {checked}/{len(urls)} — changed {changed_n}, first {first_n}, fail {fail_n}"
                        )

            Actor.log.info(
                f"{len(urls)} URL(s); concurrency={conc}; selector={css_selector!r}; filter={out_filter}"
            )
            await Actor.set_status_message(f"Monitoring {len(urls)} URL(s)…")
            await asyncio.gather(*(one(u) for u in urls))
            async with lock:
                await flush(force=True)

        peak_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
        summary = {
            "totalChecked": checked,
            "saved": saved,
            "ok": ok_n,
            "failed": fail_n,
            "changed": changed_n,
            "firstSeen": first_n,
            "byClass": dict(class_counts),
            "outputFilter": out_filter,
            "cssSelector": css_selector,
            "storePreviousText": store_text,
            "chargeFailedChecks": charge_failed,
            "inputUrls": len(urls),
            "maxUrlsReached": max_urls is not None and checked >= max_urls,
            "charged": dict(charger.counts),
            "durationSecs": round(time.time() - t0, 1),
            "peakMemoryMb": peak_mb,
            "finishedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        store = await Actor.open_key_value_store()
        await store.set_value("SUMMARY", summary)
        await store.set_value("OUTPUT", summary)
        msg = (
            f"Done: checked {checked}, saved {saved}; changed {changed_n}, first {first_n}, fail {fail_n}. "
            f"Charged: {charger.counts or 'nothing'}."
        )
        Actor.log.info(msg + f" Peak memory {peak_mb} MB, {summary['durationSecs']} s.")
        await Actor.set_status_message(msg, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
