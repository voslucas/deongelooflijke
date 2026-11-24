# Local person portraits

Both site builders prefetch the selected Wikipedia person images and serve local
JPEGs. This covers episode sidebars, the persons overview, person detail pages,
and related-person recommendations. Missing images show initials; browsers never
fall back to Wikimedia thumbnail services. Guest/host photos already stored in
`data/persons/images/` keep their existing workflow.

`scripts/person_images.py` reads `wiki_image` from `data/analysis/*.json` and
`data/persons_mentioned/*.json`. It includes new episodes before person detail
records exist. It downloads only selected matches, never search candidates from
`wiki_cache.json`, and makes no searches or model calls. Source metadata and
Wikipedia article links are retained. Wikimedia thumbnail sizes are normalized
to 250px, so old 240px links and their 250px equivalents share a cached image.

Images and `index.json` live in `data/person_images/` and should be committed
alongside episode data, just like book covers. Filenames are hashes of source
URLs; the manifest retains source URLs for traceability. Downloads have a 12-second
timeout and 8 MiB limit, are validated with Pillow, resized to fit 320 by 320
pixels, and re-encoded as JPEG without source metadata. Two downloads can run
concurrently. Existing valid files are reused. Failed downloads are retried after
24 hours and do not prevent the site from building. Image licensing and credit
requirements still apply; local caching does not change the source license.

```powershell
# Prefetch all selected portraits.
python scripts/person_images.py

# Immediately retry failed downloads.
python scripts/person_images.py --retry-missing

# Build production pages from cached covers and portraits, without downloads.
python scripts/5b_build_site.py --offline

# Build production pages and immediately retry missing portraits.
python scripts/5b_build_site.py --retry-missing-person-images
```

Both `5b_build_site.py` and the legacy `5_build_site.py` run this automatically.
They publish images under `data/person_images/` in their output directory; the
manifest is not published. The legacy builder embeds a source-to-local URL map
for its renderers. The original source URLs remain in metadata for future runs.

The daily new-episode workflow prefetches portraits after enrichment and includes
the cache in its existing `data/` commit. It also runs on days with no pending
episodes, allowing failed downloads to recover. The Pages build independently
prefetches missing images, so a new episode needs no manual image step. For local
episode processing, the next normal site build performs the prefetch; running the
standalone command warms the cache without building the site.

Run `python -m pytest tests/test_person_images.py tests/test_static_build.py -q`
to check image validation, deduplication, cache reuse, retries, new-episode
collection, and local rendering in both site versions.
