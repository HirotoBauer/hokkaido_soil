#!/usr/bin/env python3
"""
Download SMAP 400m files from a UVA Dataverse dataset for June-August of a
range of years, based on the REAL date embedded in each file's filename
(not a guessed file-id offset), downloading ONE FILE AT A TIME.

Filename pattern observed: smap_sm_400m_YYYYDOY.tif
    e.g. smap_sm_400m_2016162.tif -> year 2016, day-of-year 162

Workflow:
    1. Fetch the dataset's file listing ONCE via the Dataverse API
       (this returns every file's id + real filename + metadata, no file
       content downloaded).
    2. Parse the year/DOY out of each filename and convert to a real date.
    3. Filter to files whose date falls in June-August of the requested
       year range (and optionally on/after --start-date).
    4. Skip any file whose filename already exists in --out-dir.
    5. Download each remaining file individually via
       GET /api/access/datafile/{id}, retrying with increasing delay on
       failure (including AWS WAF bot-challenge detection and Dataverse's
       own "still preparing" 202 responses).
    6. Write CSVs for:
        - unparseable_filenames.csv: files whose name didn't match the
          expected pattern (so a date could not be determined)
        - failed_downloads.csv: files that could not be downloaded after
          all retries

Usage:
    python download_smap.py --api-key YOUR_TOKEN
    python download_smap.py --api-key YOUR_TOKEN --start-date 2018-07-15
    python download_smap.py --api-key YOUR_TOKEN --start-year 2015 --end-year 2023
"""

import argparse
import csv
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

SERVER = "https://dataverse.lib.virginia.edu"
PERSISTENT_ID = "doi:10.18130/V3/IVOU1T"

FILES_LIST_URL = f"{SERVER}/api/datasets/:persistentId/versions/:latest/files"
SINGLE_FILE_URL = f"{SERVER}/api/access/datafile/{{}}"

# smap_sm_400m_YYYYDOY.tif  (DOY zero-padded to 3 digits)
FILENAME_PATTERN = re.compile(r"smap_sm_400m_(\d{4})(\d{3})\.tif$", re.IGNORECASE)

MAX_RETRIES = 10
INITIAL_BACKOFF = 2.0
BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF = 300.0
REQUEST_TIMEOUT = 60

POLL_202_INTERVAL = 5.0
POLL_202_MAX_POLLS = 3

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def build_headers(api_key: str) -> dict:
    headers = dict(REQUEST_HEADERS)
    if api_key:
        headers["X-Dataverse-key"] = api_key
    return headers


def doy_to_date(year: int, doy: int) -> date:
    return date(year, 1, 1) + timedelta(days=doy - 1)


def fetch_file_list(session: requests.Session, headers: dict) -> list[dict]:
    """Fetch the full list of {id, filename} for every file in the dataset."""
    params = {"persistentId": PERSISTENT_ID}
    resp = session.get(
        FILES_LIST_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    payload = resp.json()

    entries = payload.get("data", [])
    files = []
    for entry in entries:
        data_file = entry.get("dataFile", {})
        file_id = data_file.get("id")
        filename = entry.get("label") or data_file.get("filename")
        if file_id is not None and filename:
            files.append({"id": file_id, "filename": filename})
    return files


def classify_files(
    files: list[dict], start_year: int, end_year: int, start_date_filter
):
    """
    Split files into:
      - matched: [{id, filename, date}] within Jun-Aug of the year range
                 (and >= start_date_filter if given)
      - unparseable: [{id, filename}] whose name didn't match the pattern
    """
    matched = []
    unparseable = []

    for f in files:
        m = FILENAME_PATTERN.search(f["filename"])
        if not m:
            unparseable.append(f)
            continue

        year = int(m.group(1))
        doy = int(m.group(2))
        try:
            d = doy_to_date(year, doy)
        except ValueError:
            unparseable.append(f)
            continue

        if d.month not in (6, 7, 8):
            continue
        if not (start_year <= d.year <= end_year):
            continue
        if start_date_filter and d < start_date_filter:
            continue

        matched.append({"id": f["id"], "filename": f["filename"], "date": d})

    return matched, unparseable


def download_one_file(
    session: requests.Session, headers: dict, file_id: int, filename: str, out_dir: Path
) -> tuple[bool, str]:
    """
    Download a single file by id, saving it under its real filename.
    Retries up to MAX_RETRIES times with increasing delay, handling AWS WAF
    bot-challenge responses and Dataverse's async-preparation 202 responses.
    Returns (success, error_message).
    """
    url = SINGLE_FILE_URL.format(file_id)
    dest = out_dir / filename
    tmp_dest = out_dir / (filename + ".part")
    delay = INITIAL_BACKOFF
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(
                url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                headers=headers,
            )

            if resp.headers.get("x-amzn-waf-action") == "challenge":
                raise IOError(
                    "blocked by AWS WAF bot challenge (x-amzn-waf-action: challenge). "
                    "A plain script request cannot pass this."
                )

            poll_count = 0
            while resp.status_code == 202:
                if poll_count >= POLL_202_MAX_POLLS:
                    print(
                        f"    file {file_id} still returning 202 after {poll_count} polls. Full response info:"
                    )
                    print(f"      status: {resp.status_code}")
                    print(f"      headers: {dict(resp.headers)}")
                    try:
                        body_preview = resp.text[:500]
                    except Exception:
                        body_preview = "<could not read body as text>"
                    print(f"      body preview: {body_preview!r}")
                    raise IOError(
                        f"file {file_id} stuck at 202 after {poll_count} polls; see diagnostics above"
                    )

                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else POLL_202_INTERVAL
                print(
                    f"    file {file_id} not ready yet (202), waiting {wait:.0f}s... "
                    f"(poll {poll_count + 1}/{POLL_202_MAX_POLLS})"
                )
                time.sleep(wait)
                poll_count += 1
                resp = session.get(
                    url,
                    stream=True,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                    headers=headers,
                )
                if resp.headers.get("x-amzn-waf-action") == "challenge":
                    raise IOError(
                        "blocked by AWS WAF bot challenge (x-amzn-waf-action: challenge) while polling."
                    )

            resp.raise_for_status()

            bytes_written = 0
            with open(tmp_dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bytes_written += len(chunk)

            if bytes_written == 0:
                content_length = resp.headers.get("Content-Length", "unknown")
                raise IOError(
                    f"downloaded file is empty (0 bytes). status={resp.status_code}, "
                    f"content-length={content_length}"
                )

            tmp_dest.rename(dest)
            return True, ""

        except Exception as e:
            last_error = str(e)
            if tmp_dest.exists():
                tmp_dest.unlink()
            print(
                f"    [attempt {attempt}/{MAX_RETRIES}] failed for file {file_id} ({filename}): {last_error}"
            )
            if attempt < MAX_RETRIES:
                print(f"    retrying in {delay:.1f}s...")
                time.sleep(delay)
                delay = min(delay * BACKOFF_MULTIPLIER, MAX_BACKOFF)

    return False, last_error


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--api-key", default="", help="Dataverse API token (X-Dataverse-key)"
    )
    parser.add_argument(
        "--out-dir",
        default=str(SCRIPT_DIR),
        help="Directory to save files (default: script's directory)",
    )
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2023)
    parser.add_argument(
        "--start-date",
        default=None,
        help="Optional YYYY-MM-DD to skip everything before this date",
    )
    parser.add_argument("--unparseable-csv", default="unparseable_filenames.csv")
    parser.add_argument("--failed-csv", default="failed_downloads.csv")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    start_date_filter = None
    if args.start_date:
        y, m, d = (int(x) for x in args.start_date.split("-"))
        start_date_filter = date(y, m, d)

    headers = build_headers(args.api_key)
    session = requests.Session()

    print("Fetching file list from dataset metadata...")
    all_files = fetch_file_list(session, headers)
    print(f"  dataset contains {len(all_files)} files total")

    matched, unparseable = classify_files(
        all_files, args.start_year, args.end_year, start_date_filter
    )
    print(
        f"  {len(matched)} files match Jun-Aug {args.start_year}-{args.end_year}"
        + (f" (from {start_date_filter})" if start_date_filter else "")
    )
    print(f"  {len(unparseable)} files had unparseable filenames (date unknown)")

    to_download = [f for f in matched if not (out_dir / f["filename"]).exists()]
    already_have = len(matched) - len(to_download)
    if already_have:
        print(f"  {already_have} already downloaded, skipping")
    print(f"  {len(to_download)} files to download\n")

    failed_rows = []
    downloaded = 0

    for i, f in enumerate(to_download, start=1):
        print(f"[{i}/{len(to_download)}] {f['date']} -> id {f['id']} ({f['filename']})")
        success, err = download_one_file(
            session, headers, f["id"], f["filename"], out_dir
        )

        if success:
            downloaded += 1
            print(f"  saved to {out_dir / f['filename']}")
        else:
            print(f"  giving up on {f['filename']} after {MAX_RETRIES} attempts: {err}")
            failed_rows.append(
                {
                    "date": f["date"].isoformat(),
                    "file_id": f["id"],
                    "filename": f["filename"],
                    "error": err,
                }
            )

    unparseable_path = Path(args.unparseable_csv)
    with open(unparseable_path, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["id", "filename"])
        writer.writeheader()
        writer.writerows(unparseable)

    failed_path = Path(args.failed_csv)
    with open(failed_path, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["date", "file_id", "filename", "error"])
        writer.writeheader()
        writer.writerows(failed_rows)

    print("\n--- Summary ---")
    print(f"Downloaded this run: {downloaded}")
    print(f"Already had: {already_have}")
    print(f"Failed: {len(failed_rows)} -> {failed_path}")
    print(f"Unparseable filenames: {len(unparseable)} -> {unparseable_path}")


if __name__ == "__main__":
    main()
