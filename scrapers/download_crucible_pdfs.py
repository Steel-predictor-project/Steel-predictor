"""Download Crucible Industries CPM steel datasheets.

Uses Wayback Machine as fallback when crucible.com is unreachable.
"""
import os
import requests
import time

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")
os.makedirs(PDF_DIR, exist_ok=True)

PDFS = {
    "CPM_S30V": "https://crucible.com/PDFs/%5CDataSheets2010%5CdsS30Vv1%202010.pdf",
    "CPM_S35VN": "https://crucible.com/PDFs//DataSheets2010/dsS35VNrev12010.pdf",
    "CPM_S45VN": "https://crucible.com/PDFs/DataSheets2010/dsS45VN%20rev%202.pdf",
    "CPM_S90V": "https://crucible.com/PDFs/DataSheets2010/dsS90v1%202010.pdf",
    "CPM_S110V": "https://crucible.com/PDFs%5CDataSheets2010%5CDatasheet%20CPM%20S110Vv12010.pdf",
    "CPM_S125V": "https://tinkoknives.com/wp-content/uploads/2021/11/CPM-S125V.pdf",
    "CPM_MagnaCut": "https://nsm-ny.com/content/uploads/2021/07/CPM-MagnaCut-datasheet15.pdf",
    "CPM_154": "https://www.crucible.com/PDFs/DataSheets2010/Datasheet%20CPM%20154%20CMv12010.pdf",
    "CPM_3V": "https://crucible.com/PDFs/DataSheets2010/ds3Vv1%202010.pdf",
    "CPM_4V": "https://crucible.com/PDFs/DataSheets2010/Data%20Sheet%204V.pdf",
    "CPM_10V": "https://crucible.com/PDFs/DataSheets2010/ds10Vv1%202010.pdf",
    "CPM_20CV": "https://crucible.com/PDFs%5CDataSheets2010%5CDatasheet%20CPM%2020CV.pdf",
    "CPM_1V": "https://crucible.com/PDFs/DataSheets2010/ds1Vv1%202010.pdf",
    "CPM_9V": "https://crucible.com/PDFs/DataSheets2010/ds9Vv1%202010.pdf",
    "CPM_15V": "https://crucible.com/PDFs/DataSheets2010/ds15Vv1%202010.pdf",
    "CPM_D2": "https://crucible.com/PDFs/DataSheets2010/dsD2v1%202010.pdf",
    "CPM_M4": "https://crucible.com/PDFs/DataSheets2010/dsM4v1%202010.pdf",
    "CPM_Rex_45": "https://crucible.com/PDFs/DataSheets2010/ds45rev12010.pdf",
    "CPM_Rex_76": "https://crucible.com/PDFs/DataSheets2010/ds76rev1%202010.pdf",
    "CPM_Rex_121": "https://crucible.com/PDFs/DataSheets2010/ds121v1%202010.pdf",
    "154_CM": "https://crucible.com/PDFs//DataSheets2010/ds154cmv12010.pdf",
}

# Alternate direct URLs to try
ALTERNATES = {
    "CPM_3V": [
        "https://crucible.com/PDFs/DataSheets2010/ds3Vv12010.pdf",
    ],
    "CPM_D2": [
        "https://crucible.com/PDFs/DataSheets2010/dsD2v12010.pdf",
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def wayback_url(original_url):
    """Build Wayback Machine download URL (raw content, no toolbar)."""
    # Use 'id_' flag to get raw content without the Wayback toolbar
    return f"https://web.archive.org/web/2024id_/{original_url}"


def try_download(url, timeout=30):
    """Attempt to download from a URL. Returns content bytes or None."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            ct = resp.headers.get("Content-Type", "")
            if "pdf" in ct.lower() or resp.content[:5] == b"%PDF-":
                return resp.content
    except Exception:
        pass
    return None


def download_pdf(name, url):
    """Download a single PDF with fallbacks. Returns (path, actual_url) or (None, None)."""
    path = os.path.join(PDF_DIR, f"{name}.pdf")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        print(f"  [SKIP] {name} already downloaded ({os.path.getsize(path)} bytes)")
        return path, url

    # Build list of URLs to try: direct, alternates, then Wayback for each
    urls_to_try = [url] + ALTERNATES.get(name, [])
    # For crucible.com URLs, also try www.crucible.com variant
    if "crucible.com" in url and "www.crucible.com" not in url:
        urls_to_try.append(url.replace("crucible.com", "www.crucible.com"))

    # Try direct URLs first (with short timeout)
    for try_url in urls_to_try:
        content = try_download(try_url, timeout=10)
        if content:
            with open(path, "wb") as f:
                f.write(content)
            print(f"  [OK]   {name} ({len(content)} bytes) direct: {try_url}")
            return path, try_url

    # Try Wayback Machine for all URLs
    for try_url in urls_to_try:
        wb = wayback_url(try_url)
        content = try_download(wb, timeout=30)
        if content:
            with open(path, "wb") as f:
                f.write(content)
            print(f"  [OK]   {name} ({len(content)} bytes) via Wayback")
            return path, try_url
        time.sleep(0.5)

    print(f"  [FAIL] {name} — all URLs failed")
    return None, None


def main():
    print("Downloading Crucible Industries PDFs...")
    results = {}
    for name, url in PDFS.items():
        path, actual_url = download_pdf(name, url)
        results[name] = {"path": path, "url": actual_url}
        time.sleep(0.3)

    success = sum(1 for v in results.values() if v["path"])
    fail = sum(1 for v in results.values() if not v["path"])
    print(f"\nDone: {success} downloaded, {fail} failed")
    failed_names = [k for k, v in results.items() if not v["path"]]
    if failed_names:
        print(f"Failed: {', '.join(failed_names)}")
    return results


if __name__ == "__main__":
    main()
