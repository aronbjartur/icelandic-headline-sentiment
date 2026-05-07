import argparse
import json
import math
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sameiginlegt import JSON_HEADERS, finna_output, hreinsa_html_brot, hreinsa_texta, vista_csv


API_BASE_URL = "https://www.dv.is/wp-json/wp/v2/posts"
FIELDNAMES = [
    "midill",
    "sida",
    "id",
    "slug",
    "fyrirsogn",
    "lysing",
    "flokkur",
    "flokkar",
    "merki",
    "hofundur",
    "dagsetning",
    "slod",
    "mynd",
]


def build_api_url(page, per_page):
    query = urlencode({"page": page, "per_page": per_page, "_embed": "1"})
    return f"{API_BASE_URL}?{query}"


def saekja_json(url):
    request = Request(url, headers=JSON_HEADERS)
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
        headers = {key.lower(): value for key, value in response.headers.items()}
    return json.loads(body), headers


def finna_nofn(post, taxonomy):
    nofn = []
    for group in (post.get("_embedded", {}).get("wp:term") or []):
        for term in group:
            if term.get("taxonomy") != taxonomy:
                continue
            nafn = hreinsa_texta(term.get("name", ""))
            if nafn and nafn not in nofn:
                nofn.append(nafn)
    return nofn


def finna_hofund(post):
    hofundar = post.get("_embedded", {}).get("author") or []
    return hreinsa_texta(hofundar[0].get("name", "")) if hofundar else ""


def finna_mynd(post):
    mynd = hreinsa_texta(post.get("jetpack_featured_media_url", ""))
    if mynd:
        return mynd
    myndir = post.get("_embedded", {}).get("wp:featuredmedia") or []
    return hreinsa_texta(myndir[0].get("source_url", "")) if myndir else ""


def post_i_row(post, page, include_content=False):
    flokkar = finna_nofn(post, "category")
    merki = finna_nofn(post, "post_tag")
    row = {
        "midill": "DV",
        "sida": page,
        "id": post.get("id", ""),
        "slug": hreinsa_texta(post.get("slug", "")),
        "fyrirsogn": hreinsa_html_brot(post.get("title", {}).get("rendered", "")),
        "lysing": hreinsa_html_brot(post.get("excerpt", {}).get("rendered", ""), taka_lesa_meira=True),
        "flokkur": flokkar[0] if flokkar else "",
        "flokkar": " | ".join(flokkar),
        "merki": " | ".join(merki),
        "hofundur": finna_hofund(post),
        "dagsetning": hreinsa_texta(post.get("date", "")),
        "slod": hreinsa_texta(post.get("link", "")),
        "mynd": finna_mynd(post),
    }
    if include_content:
        row["efni"] = hreinsa_html_brot(post.get("content", {}).get("rendered", ""))
    return row


def skafa_dv(sidur=10, fra_sidu=1, per_page=100, bid=0.3, output_path=None, include_content=False, mark_fjoldi=None):
    rows = []
    seen = set()
    total_pages = None
    fieldnames = FIELDNAMES + (["efni"] if include_content else [])
    print("DV")

    for page in range(fra_sidu, fra_sidu + sidur):
        if total_pages is not None and page > total_pages:
            break

        print(f"{page}")
        try:
            posts, headers = saekja_json(build_api_url(page, per_page))
        except HTTPError as exc:
            if exc.code == 400:
                break
            print(exc)
            break
        except Exception as exc:
            print(exc)
            break

        if total_pages is None:
            total_pages = int(headers.get("x-wp-totalpages", "0") or 0)
        if not posts:
            break

        nyjar = 0
        for post in posts:
            post_id = post.get("id")
            if post_id in seen:
                continue
            seen.add(post_id)
            rows.append(post_i_row(post, page, include_content=include_content))
            nyjar += 1

        print(f"{len(posts)} -> {nyjar}")
        if mark_fjoldi is not None and len(rows) >= mark_fjoldi:
            rows = rows[:mark_fjoldi]
            break
        time.sleep(bid)

    if not rows:
        print("Engin gogn")
        return None

    output_path = finna_output(output_path, "dv_gogn.csv")
    vista_csv(rows, output_path, fieldnames)
    print(f"{len(rows)} -> {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidur", type=int, default=10)
    parser.add_argument("--fra-sidu", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--bid", type=float, default=0.3)
    parser.add_argument("--output")
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--fjoldi", type=int)
    args = parser.parse_args()

    if args.sidur < 1 or args.fra_sidu < 1:
        raise ValueError("Rangt input")
    if args.per_page < 1 or args.per_page > 100:
        raise ValueError("Rangt input")
    if args.fjoldi is not None and args.fjoldi < 1:
        raise ValueError("Rangt input")

    sidur = args.sidur
    if args.fjoldi is not None:
        sidur = max(args.sidur, math.ceil(args.fjoldi / args.per_page))

    skafa_dv(
        sidur=sidur,
        fra_sidu=args.fra_sidu,
        per_page=args.per_page,
        bid=args.bid,
        output_path=args.output,
        include_content=args.include_content,
        mark_fjoldi=args.fjoldi,
    )


if __name__ == "__main__":
    main()
