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
Invalid images, tiny placeholders, and Google's recognized "image not available"
image are rejected. Successful images are resized
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

## One-time Open Library repair

`scripts/repair_books_openlibrary.py` repairs missing detail records, incomplete
metadata, and unavailable covers without Google Books or model calls. It includes
books with no ISBN or Google volume ID. Existing route keys remain unchanged;
the static detail loader also registers those original keys when an ISBN is found.

```powershell
.\.venv\Scripts\python.exe scripts/repair_books_openlibrary.py --apply
# Use direct HTTPS when local environment proxies are unavailable:
.\.venv\Scripts\python.exe scripts/repair_books_openlibrary.py --apply --direct
# Retry searches that could not be matched confidently:
.\.venv\Scripts\python.exe scripts/repair_books_openlibrary.py --apply --direct --retry-unresolved
```

ISBN matches identify an edition. Title searches require a close title and a
matching author, including author aliases supplied by Open Library. Subtitle-free
searches help locate works whose catalogue titles differ. Dutch and classical
recommended titles prefer Dutch editions; explicit English titles retain English
editions. Existing ISBNs are retained unless a preferred Dutch edition is selected.
Edition metadata is copied together rather than borrowing page counts or publishers
from another edition. Work descriptions may fill gaps across editions.

The script downloads selected covers into the existing versioned cache and updates
analysis cover URLs without changing their ISBNs or Google IDs. It recognizes the
Google placeholder image identified during this repair. `data/book_repair_report.json`
records outcomes, changed fields, matched works/editions, and remaining gaps. API
responses are cached in the system temporary directory so interrupted runs can
resume. Requests share a one-per-second limiter. This is a manual repair tool;
the daily pipeline is unchanged. After applying repairs, run stage 4 and the
static builder with `--offline` to publish the repaired local data.

For Dutch records that Open Library cannot complete, run the separate one-time
catalogue fallback:

```powershell
.\.venv\Scripts\python.exe scripts/repair_books_bibliotheek.py --apply
```

It searches Bibliotheek.nl's public print catalogue by ISBN first, then by title
and the primary author's surname when the original edition is unavailable. Title
and author are checked before selecting an alternative Dutch edition. Single-edition
and multiple-edition catalogue layouts are supported. Selected print covers are
downloaded immediately from the catalogue's signed image URLs; visitors continue
to use local JPEGs. The selected ISBN, publisher, year, page count, catalogue URL
and PPN are stored together. Original archive keys remain valid. Results and
remaining gaps are recorded in `data/book_repair_bibliotheek_report.json`.

Run these two repair scripts sequentially when applying changes, since both update
the shared book records and cover manifest. A read-only run can warm catalogue
responses while another script is applying metadata. Neither script is added to
the daily pipeline.

After both providers finish, unidentified duplicates can reuse a verified local
edition without more HTTP requests:

```powershell
.\.venv\Scripts\python.exe scripts/repair_books_bibliotheek.py --apply --reuse-only
```

This requires a matching author and primary title, allowing small spelling
differences with the same word count. Series titles are not assigned to individual
volumes. Original route keys remain valid. The local joins are listed separately
in `data/book_repair_alias_report.json`.
