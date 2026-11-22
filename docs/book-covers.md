# Local book covers

Both site builders serve book covers from local JPEG files. Visitors do not
request cover images from Google Books or Open Library. The existing book
matching in `analyze_episode.py` and `9_enrich_books_detail.py` is unchanged.

## Selection and download

`scripts/book_covers.py` reads book details in `data/books/` and book mentions in
`data/analysis/`. Reading analysis directly includes books in new episodes even
before a full book detail record exists. Records are joined by their existing
ISBN, selected Google Books volume ID, or stored cover URL, never by title alone.

For each selected edition, the downloader tries:

1. Open Library's large cover for its ISBN-13, with `default=false` so missing
   covers return an error instead of Open Library's default image.
2. The stored Google Books cover URLs, with expired tokens removed and thumbnail
   size normalized.
3. A Google Books cover URL constructed from the already-selected volume ID.

Google candidates are deduplicated and tried in a stable order. No new book
searches or model calls are made. Provider requests occur on the build machine.
Invalid images and tiny placeholders are rejected. Successful images are resized
to fit 640 by 960 pixels, converted to JPEG, and saved without source metadata.
If all sources fail, the site shows its gold book icon without a remote fallback.

## Builds and incremental processing

`5b_build_site.py` and `5_build_site.py` call the downloader automatically. No
additional step is needed when a new episode's analysis introduces another book.
The downloaded covers are stored in `data/book_covers/`, with an identity manifest
at `index.json`. Both the JPEGs and manifest are versioned in Git; only temporary
download files are ignored.
Existing valid files are reused; unavailable covers are retried after 24 hours.
There are at most four simultaneous book download jobs.

```powershell
# Warm the cache independently.
.\.venv\Scripts\python.exe scripts/book_covers.py

# Retry unavailable covers immediately.
.\.venv\Scripts\python.exe scripts/book_covers.py --retry-missing

# Build the production site using cached covers only.
.\.venv\Scripts\python.exe scripts/5b_build_site.py --offline

# Build and immediately retry covers that previously failed.
.\.venv\Scripts\python.exe scripts/5b_build_site.py --retry-missing-covers
```

The generated images live in `site/static/data/book_covers/` or
`site/dist/data/book_covers/`. The manifest stays in the build cache and is not
published. Source book metadata retains the original provider URLs for future
downloads, but image elements reference only generated local files.

The shared renderers cover episode book sidebars, overview cards and rows,
individual book covers, and related-book recommendations in both site versions.

## CI and validation

The Pages workflow installs Pillow and uses the covers checked out from Git.
It still downloads missing covers during the normal build. An Actions cache is
not restored over this directory, so older cached metadata cannot overwrite
versioned cover choices. Failed image requests do not prevent the rest of the
archive from building.

The daily new-episode workflow downloads missing covers after analysis and includes
the JPEGs and manifest in its data commit. For local processing, include changes
under `data/book_covers/` in the commit alongside the episode data. The Pages build
itself publishes new downloads without pushing commits back to the repository.

Pillow is included in `requirements.txt`. Cover tests verify Open Library to
Google fallback, edition identity, newly analyzed books without detail records,
cache reuse, retry behavior, corrupt-image replacement, and all production
cover rendering locations.
