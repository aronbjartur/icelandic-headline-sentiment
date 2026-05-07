import argparse
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from sameiginlegt import HEADERS, finna_output, hreinsa_html_brot, hreinsa_texta, vista_csv


BASE_URL = "https://www.visir.is"
VISIR_DEILDIR = {
    "frettir": {"nafn": "Fréttir", "url": "https://www.visir.is/f/frettir/{page}"},
    "sport": {"nafn": "Sport", "url": "https://www.visir.is/f/sport/{page}"},
}
DEFAULT_DEILDIR = ("frettir", "sport")
FIELDNAMES = [
    "midill",
    "deild",
    "sida",
    "fyrirsogn",
    "lysing",
    "flokkur",
    "dagsetning",
    "slod",
    "mynd",
]

ARTICLE_RE = re.compile(
    r'<article\b[^>]*class="[^"]*article-item[^"]*"[^>]*>(.*?)</article>',
    re.DOTALL | re.IGNORECASE,
)
TITLE_RE = re.compile(
    r'<h[1-6][^>]*class="[^"]*article-item__title[^"]*"[^>]*>\s*'
    r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
TIME_RE = re.compile(
    r'<time[^>]*class="[^"]*article-item__time[^"]*"[^>]*>(.*?)</time>',
    re.DOTALL | re.IGNORECASE,
)
CATEGORY_RE = re.compile(
    r'<(?:a|div)[^>]*class="[^"]*badge[^"]*badge--tag[^"]*"[^>]*>(.*?)</(?:a|div)>',
    re.DOTALL | re.IGNORECASE,
)
SUMMARY_RE = re.compile(
    r'<p[^>]*class="[^"]*(?:article-item__text|-large)[^"]*"[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)
IMAGE_RE = re.compile(r'<img[^>]*src="([^"]+)"', re.DOTALL | re.IGNORECASE)


def parse_deildir(raw_value):
    if not raw_value:
        return list(DEFAULT_DEILDIR)
    deildir = []
    for item in raw_value.split(","):
        deild = item.strip().lower()
        if not deild:
            continue
        if deild not in VISIR_DEILDIR:
            raise ValueError(f"Óstudd deild: {deild}")
        if deild not in deildir:
            deildir.append(deild)
    if not deildir:
        raise ValueError("Engar deildir")
    return deildir


def parse_visir_html(html_doc, page_url, page_number, deild):
    if "pdf2htmlEX" in html_doc or 'name="generator" content="pdf2htmlEX"' in html_doc:
        raise ValueError("Rangt html")

    rows = []
    seen = set()
    for match in ARTICLE_RE.finditer(html_doc):
        article_html = match.group(0)
        title_match = TITLE_RE.search(article_html)
        time_match = TIME_RE.search(article_html)
        if title_match is None or time_match is None:
            continue

        href = hreinsa_texta(title_match.group(1))
        if not href:
            continue

        slod = urljoin(page_url, href)
        if slod in seen:
            continue
        seen.add(slod)

        category_match = CATEGORY_RE.search(article_html)
        summary_match = SUMMARY_RE.search(article_html)
        image_match = IMAGE_RE.search(article_html)
        rows.append(
            {
                "midill": "Visir",
                "deild": VISIR_DEILDIR[deild]["nafn"],
                "sida": page_number,
                "fyrirsogn": hreinsa_html_brot(title_match.group(2)),
                "lysing": hreinsa_html_brot(summary_match.group(1) if summary_match else ""),
                "flokkur": hreinsa_html_brot(category_match.group(1) if category_match else ""),
                "dagsetning": hreinsa_html_brot(time_match.group(1)),
                "slod": slod,
                "mynd": urljoin(page_url, image_match.group(1)) if image_match else "",
            }
        )

    if not rows:
        raise ValueError("Engar greinar")
    return rows


def saekja_html(url):
    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=20) as response:
        body = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
    return body.decode(encoding, errors="replace")


def skafa_visi(sidur=40, fra_sidu=1, bid=1.0, output_path=None, deildir=None, mark_fjoldi=None):
    deildir = list(DEFAULT_DEILDIR) if deildir is None else deildir
    rows = []
    seen = set()
    lokid = set()
    page = fra_sidu
    sidasti = None if sidur is None else fra_sidu + sidur - 1
    print("Visir")

    while True:
        if sidasti is not None and page > sidasti:
            break
        if len(lokid) == len(deildir):
            break

        stoppa = False
        for deild in deildir:
            if deild in lokid:
                continue

            config = VISIR_DEILDIR[deild]
            url = config["url"].format(page=page)
            print(f"{config['nafn']} {page}")

            try:
                gogn = parse_visir_html(saekja_html(url), url, page, deild)
            except HTTPError as exc:
                if exc.code == 404:
                    lokid.add(deild)
                    continue
                print(exc)
                stoppa = True
                break
            except ValueError:
                lokid.add(deild)
                continue
            except Exception as exc:
                print(exc)
                stoppa = True
                break

            nyjar = 0
            for grein in gogn:
                if grein["slod"] in seen:
                    continue
                seen.add(grein["slod"])
                rows.append(grein)
                nyjar += 1

            print(f"{len(gogn)} -> {nyjar}")
            if mark_fjoldi is not None and len(rows) >= mark_fjoldi:
                rows = rows[:mark_fjoldi]
                stoppa = True
                break
            time.sleep(bid)

        if stoppa:
            break
        page += 1

    if not rows:
        print("Engin gogn")
        return None

    output_path = finna_output(output_path, "visir_gogn.csv")
    vista_csv(rows, output_path, FIELDNAMES)
    print(f"{len(rows)} -> {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidur", type=int, default=40)
    parser.add_argument("--fra-sidu", type=int, default=1)
    parser.add_argument("--bid", type=float, default=1.0)
    parser.add_argument("--deildir", default="frettir,sport")
    parser.add_argument("--output")
    parser.add_argument("--fjoldi", type=int)
    parser.add_argument("--html-skra")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    if args.sidur < 1 or args.fra_sidu < 1:
        raise ValueError("Rangt input")
    if args.fjoldi is not None and args.fjoldi < 1:
        raise ValueError("Rangt input")

    deildir = parse_deildir(args.deildir)

    if args.html_skra:
        html_doc = Path(args.html_skra).read_text(encoding="utf-8")
        rows = parse_visir_html(html_doc, args.base_url, args.fra_sidu, deildir[0])
        output_path = finna_output(args.output, "visir_gogn.csv")
        vista_csv(rows, output_path, FIELDNAMES)
        print(f"{len(rows)} -> {output_path}")
        return

    skafa_visi(
        sidur=None if args.fjoldi is not None else args.sidur,
        fra_sidu=args.fra_sidu,
        bid=args.bid,
        output_path=args.output,
        deildir=deildir,
        mark_fjoldi=args.fjoldi,
    )


if __name__ == "__main__":
    main()
