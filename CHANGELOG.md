## 0.1.2

- Fix snapshot KV keys: use `snap_<sha256>` (Apify keys disallow `:`).

## 0.1.1

- First cloud build (private).

## 0.1.0

- Initial private release: HTTP fetch, text extract (optional CSS via selectolax), SHA-256 hash, difflib diff, persistent KV snapshots, PPE (`page-checked` + `page-changed`), failed checks free by default.
