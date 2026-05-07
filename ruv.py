import argparse
import json
import math
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from sameiginlegt import GRAPHQL_HEADERS, finna_output, hreinsa_texta, vista_csv


GRAPHQL_URL = "https://gql.nyr.ruv.is/graphql/"
PUBLIC_BASE_URL = "https://www.ruv.is"
RUV_DEILDIR = {
    "all": {"nafn": "Allar frettir", "parent_slug": None},
    "innlent": {"nafn": "Innlent", "parent_slug": "innlent"},
    "erlent": {"nafn": "Erlent", "parent_slug": "erlent"},
    "ithrottir": {"nafn": "Ithrottir", "parent_slug": "ithrottir"},
    "menning-og-daegurmal": {
        "nafn": "Menning og daegurmal",
        "parent_slug": "menning-og-daegurmal",
    },
}
DEFAULT_DEILDIR = ("all",)
FIELDNAMES = [
    "midill",
    "sott_ur",
    "sida",
    "id",
    "slug",
    "deild",
    "deild_slug",
    "flokkur",
    "flokkur_slug",
    "fyrirsogn",
    "lysing",
    "tegund",
    "i_beinni",
    "hofundar",
    "merki",
    "dagsetning",
    "sidast_birt",
    "slod",
    "mynd",
    "mynd_alt",
]

MORE_ARTICLES_QUERY = """
query MoreArticles(
  $limit: Int!
  $page: Int!
  $parentSlug: String
  $dateFrom: String
  $dateTo: String
  $tag: String
  $category: String
  $articletype: String
) {
  cachedArticles(
    limit: $limit
    page: $page
    parentSlug: $parentSlug
    dateFrom: $dateFrom
    dateTo: $dateTo
    tag: $tag
    category: $category
    articletype: $articletype
  ) {
    id
    title
    subtitle
    url
    og_url
    url_path_alias
    slug
    content_type
    is_live
    first_published_at
    last_published_at
    authors {
      name
    }
    topic {
      name
      slug
      category {
        slug
        title
        color
      }
    }
    parent {
      slug
      title
      color
    }
    tags {
      name
      slug
    }
    main_image {
      renditions {
        medium {
          src
          alt
        }
      }
    }
  }
}
""".strip()
def parse_deildir(raw_value):
    if not raw_value:
        return list(DEFAULT_DEILDIR)
    deildir = []
    for item in raw_value.split(","):
        deild = item.strip().lower()
        if not deild:
            continue
        if deild not in RUV_DEILDIR:
            raise ValueError(f"Ostudd deild: {deild}")
        if deild not in deildir:
            deildir.append(deild)
    if not deildir:
        raise ValueError("Engar deildir")
    if "all" in deildir and len(deildir) > 1:
        raise ValueError("Veldu all eða hitt")
    return deildir


def saekja_json(payload):
    request = Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=GRAPHQL_HEADERS,
    )
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if "errors" in data and data["errors"]:
        raise ValueError(f"GraphQL villa: {data['errors']}")
    return data


def byggja_slod(url="", og_url="", url_path_alias=""):
    for candidate in (url_path_alias, url, og_url):
        candidate = hreinsa_texta(candidate)
        if not candidate:
            continue
        if candidate.startswith("/"):
            return f"{PUBLIC_BASE_URL}{candidate}"
        parsed = urlsplit(candidate)
        if parsed.scheme and parsed.netloc and parsed.path:
            suffix = parsed.path
            if parsed.query:
                suffix = f"{suffix}?{parsed.query}"
            return f"{PUBLIC_BASE_URL}{suffix}"
    return ""


def finna_nofn(listi, key):
    nofn = []
    for item in listi or []:
        nafn = hreinsa_texta(item.get(key, ""))
        if nafn and nafn not in nofn:
            nofn.append(nafn)
    return nofn


def finna_mynd(article, key):
    main_image = article.get("main_image") or {}
    medium = main_image.get("renditions", {}).get("medium", {})
    return hreinsa_texta(medium.get(key, ""))


def grein_i_row(article, api_page, selected_deild):
    parent = article.get("parent") or {}
    topic = article.get("topic") or {}
    hofundar = finna_nofn(article.get("authors"), "name")
    merki = finna_nofn(article.get("tags"), "name")
    return {
        "midill": "RUV",
        "sott_ur": RUV_DEILDIR[selected_deild]["nafn"],
        "sida": api_page,
        "id": article.get("id", ""),
        "slug": hreinsa_texta(article.get("slug", "")),
        "deild": hreinsa_texta(parent.get("title", "")),
        "deild_slug": hreinsa_texta(parent.get("slug", "")),
        "flokkur": hreinsa_texta(topic.get("name", "")),
        "flokkur_slug": hreinsa_texta(topic.get("slug", "")),
        "fyrirsogn": hreinsa_texta(article.get("title", "")),
        "lysing": hreinsa_texta(article.get("subtitle", "")),
        "tegund": hreinsa_texta(article.get("content_type", "")),
        "i_beinni": bool(article.get("is_live")),
        "hofundar": " | ".join(hofundar),
        "merki": " | ".join(merki),
        "dagsetning": hreinsa_texta(article.get("first_published_at", "")),
        "sidast_birt": hreinsa_texta(article.get("last_published_at", "")),
        "slod": byggja_slod(
            url=article.get("url", ""),
            og_url=article.get("og_url", ""),
            url_path_alias=article.get("url_path_alias", ""),
        ),
        "mynd": finna_mynd(article, "src"),
        "mynd_alt": finna_mynd(article, "alt"),
    }


def saekja_greinar(page, per_page, parent_slug=None):
    payload = {
        "operationName": "MoreArticles",
        "query": MORE_ARTICLES_QUERY,
        "variables": {
            "limit": per_page,
            "page": page,
            "parentSlug": parent_slug,
            "dateFrom": None,
            "dateTo": None,
            "tag": None,
            "category": None,
            "articletype": None,
        },
    }

    return saekja_json(payload).get("data", {}).get("cachedArticles", []) or []


def skafa_ruv(sidur=20, fra_sidu=1, per_page=50, bid=0.15, output_path=None, deildir=None, mark_fjoldi=None):
    deildir = list(DEFAULT_DEILDIR) if deildir is None else deildir
    rows = []
    seen = set()
    lokid = set()
    page = fra_sidu
    sidasti = None if sidur is None else fra_sidu + sidur - 1
    print("RUV")

    while True:
        if sidasti is not None and page > sidasti:
            break
        if len(lokid) == len(deildir):
            break

        for deild in deildir:
            if deild in lokid:
                continue

            print(f"{RUV_DEILDIR[deild]['nafn']} {page}")
            try:
                greinar = saekja_greinar(page, per_page, RUV_DEILDIR[deild]["parent_slug"])
            except Exception as exc:
                print(exc)
                lokid.add(deild)
                continue

            if not greinar:
                lokid.add(deild)
                continue

            nyjar = 0
            for article in greinar:
                article_id = article.get("id")
                if article_id in seen:
                    continue
                seen.add(article_id)
                rows.append(grein_i_row(article, page, deild))
                nyjar += 1

            print(f"{len(greinar)} -> {nyjar}")
            if mark_fjoldi is not None and len(rows) >= mark_fjoldi:
                rows = rows[:mark_fjoldi]
                output_path = finna_output(output_path, "ruv_gogn.csv")
                vista_csv(rows, output_path, FIELDNAMES)
                print(f"{len(rows)} -> {output_path}")
                return output_path
            time.sleep(bid)

        page += 1

    if not rows:
        print("Engin gogn")
        return None

    output_path = finna_output(output_path, "ruv_gogn.csv")
    vista_csv(rows, output_path, FIELDNAMES)
    print(f"{len(rows)} -> {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidur", type=int)
    parser.add_argument("--fra-sidu", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--bid", type=float, default=0.15)
    parser.add_argument("--deildir", default="all")
    parser.add_argument("--fjoldi", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()

    if args.sidur is not None and args.sidur < 1:
        raise ValueError("Rangt input")
    if args.fra_sidu < 1 or args.per_page < 1:
        raise ValueError("Rangt input")
    if args.fjoldi is not None and args.fjoldi < 1:
        raise ValueError("Rangt input")

    sidur = args.sidur
    if sidur is None:
        sidur = max(1, math.ceil(args.fjoldi / args.per_page)) if args.fjoldi else 20

    skafa_ruv(
        sidur=sidur,
        fra_sidu=args.fra_sidu,
        per_page=args.per_page,
        bid=args.bid,
        output_path=args.output,
        deildir=parse_deildir(args.deildir),
        mark_fjoldi=args.fjoldi,
    )


if __name__ == "__main__":
    main()
