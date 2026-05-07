import csv
import html
import re
from pathlib import Path


OUTPUT_DIR = Path("gogn")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}
JSON_HEADERS = {**HEADERS, "Accept": "application/json"}
GRAPHQL_HEADERS = {
    **JSON_HEADERS,
    "Content-Type": "application/json",
}

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def hreinsa_texta(texti):
    if not texti:
        return ""
    texti = html.unescape(texti)
    texti = texti.replace("\xad", "")
    texti = texti.replace("\xa0", " ")
    return WHITESPACE_RE.sub(" ", texti).strip()


def hreinsa_html_brot(html_brot, taka_lesa_meira=False):
    if not html_brot:
        return ""
    texti = hreinsa_texta(TAG_RE.sub(" ", html_brot))
    if taka_lesa_meira:
        texti = re.sub(r"\bLesa meira\b\s*$", "", texti, flags=re.IGNORECASE).strip()
    return texti


def finna_output(output_path, default_name):
    if output_path is None:
        return OUTPUT_DIR / default_name
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def vista_csv(rows, output_path, fieldnames):
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
