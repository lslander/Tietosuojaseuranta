"""Lähdekohtaiset hakijat.

Jokainen hakija saa lähteen konfiguraation ja palauttaa listan Item-olioita.
Uuden lähdetyypin lisääminen: kirjoita funktio ja rekisteröi se FETCHERS-sanakirjaan.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import urllib.parse
from dataclasses import dataclass, field

import feedparser
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# Yliopistojen OAI-PMH-palvelimet (Doria, Helda) katkaisevat yhteyden
# satunnaisesti kesken vastauksen ("Connection aborted"). Kolme
# uudelleenyritystä eksponentiaalisella odotuksella korjaa tämän ilman
# että lähde näyttäytyy sivulla epäonnistuneena yhden kertaluonteisen
# katkoksen takia. Sama suoja kattaa myös 502/503/504-vastaukset, joita
# tulee ajoittain valtionhallinnon Liferay-sivustoilta.
RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=1.5,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"],
)

USER_AGENT = "oikeusfeed/1.0 (henkilokohtainen oikeustapausseuranta)"

# Osa sivustoista torjuu tuntemattoman asiakasohjelman. europa.eu vastaa
# rehelliselle tunnisteelle HTTP 202 ja tyhjällä rungolla, mikä ei nosta
# virhettä vaan näyttää siltä että lähteellä ei ollut mitään uutta.
# Näille lähteille annetaan selaimen tunniste asetuksella browser: true.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
}

TIMEOUT = 45

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"


@dataclass
class Item:
    """Yksi ratkaisu feedissä."""

    source_id: str
    source_name: str
    court: str
    title: str
    url: str
    date: dt.date
    keywords: str = ""          # asiasanat, esim. "Tietosuoja – Rekisterinpitäjä"
    summary: str = ""           # vapaa tiivistelmä tai asianosaiset
    weight: int = 1             # lähteen painoarvo järjestyksessä
    score: int = 0              # täytetään suodatuksessa
    tags: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)  # täytetään suodatuksessa
    always: bool = False        # ohittaa avainsanasuodatuksen, ks. always_include

    @property
    def key(self) -> str:
        """Vakaa tunniste päällekkäisyyksien karsimiseen."""
        return self.url.split("?")[0].rstrip("/")

    def haystack(self) -> str:
        return " ".join([self.title, self.keywords, self.summary]).lower()

    def title_haystack(self) -> str:
        """Otsikko ja asiasanat ilman tiivistelmää.

        never-lista katsotaan tästä. Tiivistelmässä voi mainita ohimennen
        webinaarin tai vuosikertomuksen ilman että juttu itse on sellainen.
        Kyberturvallisuuskeskuksen viikkokatsaus 36/2026 putosi feedistä juuri
        näin, koska tiivistelmässä mainittiin CSIRT-ajankohtaiswebinaari.
        """
        return " ".join([self.title, self.keywords]).lower()


def _session(source: dict | None = None) -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=RETRY)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    if source and source.get("browser"):
        s.headers.update(BROWSER_HEADERS)
    else:
        s.headers.update({"User-Agent": USER_AGENT})
    return s


def _get(source: dict, url: str | None = None, **kwargs) -> requests.Response:
    """Hakee osoitteen ja pitää hiljaisen torjunnan virheenä.

    raise_for_status ei nosta virhettä koodista 202, joten pelkällä sillä
    estetty lähde näyttäisi sivulla vihreältä ja tyhjältä. Tyhjä runko on
    aina virhe riippumatta siitä mitä palvelin väittää statuskoodissa.
    """
    resp = _session(source).get(url or source["url"], timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    if len(resp.content) < 200:
        raise RuntimeError(
            f"palvelin vastasi {resp.status_code} ja tyhjällä rungolla "
            f"({len(resp.content)} tavua), luultavasti robottiesto"
        )
    return resp


def _parse_date(entry) -> dt.date:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return dt.date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
    return dt.date.today()


def _is_swedish_duplicate(title: str, url: str) -> bool:
    """Tuomioistuinten syötteissä sama ratkaisu tulee kahdesti, fi ja sv."""
    if "/sv/" in url or "/en/" in url:
        return True
    return bool(re.match(r"^(HD|HFD|MD|AD):", title.strip()))


# --------------------------------------------------------------------------
# Tuomioistuinlaitoksen WordPress-syötteet (KKO, KHO, MAO, TT, VakO, hovit)
# --------------------------------------------------------------------------
def fetch_wp_rss(source: dict) -> list[Item]:
    parsed = feedparser.parse(_get(source).content)

    items: list[Item] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue
        if _is_swedish_duplicate(title, url):
            continue

        # Asiasanat tulevat <category>-elementeistä. Ne ovat suodatuksen
        # tärkein signaali, koska otsikko on pelkkä "KKO:2026:62".
        cats = [c.get("term", "") for c in entry.get("tags", []) or []]
        keywords = ", ".join(c for c in cats if c)

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                court=source.get("court", source["name"]),
                title=title,
                url=url,
                date=_parse_date(entry),
                keywords=keywords,
                weight=source.get("weight", 1),
            )
        )
    return items


# --------------------------------------------------------------------------
# Tavallinen RSS tai Atom (EDPB, CURIA, mikä tahansa muu syöte)
# --------------------------------------------------------------------------
def fetch_plain_rss(source: dict) -> list[Item]:
    parsed = feedparser.parse(_get(source).content)

    items: list[Item] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue

        raw = entry.get("summary") or entry.get("description") or ""
        summary = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        # EDPB toistaa otsikon kuvauksessa. Karsitaan toisto pois.
        summary = summary.replace(title, "").strip()

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                court=source.get("court", source["name"]),
                title=title,
                url=url,
                date=_parse_date(entry),
                summary=summary[:400],
                weight=source.get("weight", 1),
            )
        )
    return items


# --------------------------------------------------------------------------
# Unionin tuomioistuin Cellarin SPARQL-rajapinnasta
# --------------------------------------------------------------------------
SPARQL_TEMPLATE = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX lang: <http://publications.europa.eu/resource/authority/language/>
SELECT DISTINCT ?celex ?date ?ecli ?lg ?parties ?subject WHERE {{
  ?work cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date .
  FILTER({celex_filter})
  FILTER(?date >= "{since}"^^<http://www.w3.org/2001/XMLSchema#date>)
  OPTIONAL {{ ?work cdm:case-law_ecli ?ecli }}
  OPTIONAL {{
    # Suomenkielinen toisinto ei ole heti saatavilla kaikista ratkaisuista,
    # joten englanti otetaan varalle ja suomi voittaa jos molemmat löytyvät.
    VALUES ?lg {{ lang:{lang} lang:ENG }}
    ?expr cdm:expression_belongs_to_work ?work ;
          cdm:expression_uses_language ?lg .
    OPTIONAL {{ ?expr cdm:expression_case-law_parties ?parties }}
    OPTIONAL {{ ?expr cdm:expression_case-law_indicator_decision ?subject }}
  }}
}}
ORDER BY DESC(?date)
LIMIT 800
"""


def fetch_eu_sparql(source: dict) -> list[Item]:
    lookback = int(source.get("lookback_days", 120))
    since = (dt.date.today() - dt.timedelta(days=lookback)).isoformat()
    lang = source.get("language", "fin").upper()
    years = {dt.date.today().year, dt.date.today().year - 1, dt.date.today().year - 2}
    types = source.get("celex_types", ["CJ", "TJ"])

    prefixes = [f"6{y}{t}" for y in sorted(years) for t in types]
    celex_filter = " || ".join(
        f'STRSTARTS(STR(?celex), "{p}")' for p in prefixes
    )

    query = SPARQL_TEMPLATE.format(
        celex_filter=celex_filter, since=since, lang=lang
    )
    resp = _session(source).get(
        SPARQL_ENDPOINT,
        params={"query": query, "format": "application/sparql-results+json"},
        timeout=180,
    )
    resp.raise_for_status()
    bindings = resp.json()["results"]["bindings"]

    # Sama celex tulee useana rivinä, yksi per kieli ja per asiasanajoukko.
    # Valitaan suomenkielinen rivi ja niistä pisin asiasanajono.
    best: dict[str, dict] = {}
    for b in bindings:
        celex = b["celex"]["value"]
        is_fin = b.get("lg", {}).get("value", "").endswith(f"/{lang}")
        row = {
            "date": b["date"]["value"],
            "ecli": b.get("ecli", {}).get("value", ""),
            "parties": b.get("parties", {}).get("value", ""),
            "subject": b.get("subject", {}).get("value", ""),
            "fin": is_fin,
        }
        prev = best.get(celex)
        if prev is None:
            best[celex] = row
            continue
        better_lang = row["fin"] and not prev["fin"]
        same_lang_longer = row["fin"] == prev["fin"] and len(row["subject"]) > len(prev["subject"])
        if better_lang or same_lang_longer:
            best[celex] = row

    items: list[Item] = []
    for celex, row in best.items():
        case_no = _celex_to_case_number(celex)
        kind = {"CJ": "tuomio", "TJ": "tuomio (unionin yleinen tuomioistuin)",
                "CC": "julkisasiamiehen ratkaisuehdotus",
                "CO": "määräys"}.get(celex[5:7], "ratkaisu")
        title = f"{case_no}, {kind}"
        if row["parties"]:
            title = f"{case_no} {row['parties'][:110]} ({kind})"

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                court=source.get("court", "EUT"),
                title=title,
                url=f"https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:{celex}",
                date=dt.date.fromisoformat(row["date"]),
                keywords=row["subject"][:600],
                summary=row["ecli"],
                weight=source.get("weight", 1),
            )
        )
    return items


def _celex_to_case_number(celex: str) -> str:
    """62024CJ0669 -> C-669/24. Yleisen tuomioistuimen asiat saavat T-tunnuksen."""
    m = re.match(r"^6(\d{4})(CJ|TJ|CC|CO)(\d{4})", celex)
    if not m:
        return celex
    year, ctype, number = m.groups()
    letter = "T" if ctype == "TJ" else "C"
    return f"{letter}-{int(number)}/{year[2:]}"


# --------------------------------------------------------------------------
# Yleinen HTML-listaus (esim. tietosuojavaltuutetun ratkaisut)
# --------------------------------------------------------------------------
def fetch_html_list(source: dict) -> list[Item]:
    soup = BeautifulSoup(_get(source).text, "html.parser")
    pattern = re.compile(source.get("link_pattern", ".")) if source.get("link_pattern") else None
    # Osa listasivuista linkittää myös omiin osastoihinsa. skip_pattern
    # pudottaa ne pois, koska pelkkä link_pattern ei erota osastosivua
    # artikkelista silloin kun ne ovat saman polun alla.
    skip = re.compile(source["skip_pattern"]) if source.get("skip_pattern") else None
    # Edilex kirjoittaa kellonajan otsikon eteen: "18.9.2026 16.00 Otsikko".
    # Se syö tilaa kortista eikä kerro mitään mitä päivämääräkenttä ei kerro.
    strip_prefix = re.compile(source["strip_title_prefix"]) if source.get("strip_title_prefix") else None
    min_len = int(source.get("min_title_len", 20))
    # Osa listasivuista ei kirjoita päivämäärää mihinkään, ei korttiin eikä
    # osoitteeseen. Silloin se haetaan jutun omalta sivulta, jos lähteessä
    # on detail_date: true. Pyyntöjä tulee yksi juttua kohden, joten tämä on
    # päällä vain niillä lähteillä joilla se on ainoa keino.
    detail = bool(source.get("detail_date"))
    max_detail = int(source.get("max_detail", 25))
    max_bytes = int(source.get("max_bytes", 400_000))
    sess = _session(source) if detail else None

    seen: set[str] = set()
    items: list[Item] = []
    resolved = 0
    for a in soup.find_all("a", href=True):
        # Osa sivustoista (ENISA) jättää href-arvoon välilyöntejä.
        href = urllib.parse.urljoin(source["url"], a["href"].strip())
        text = a.get_text(" ", strip=True)
        if href in seen:
            continue
        if pattern and not pattern.search(href):
            continue
        if skip and skip.search(href):
            continue

        if strip_prefix:
            text = strip_prefix.sub("", text, count=1).strip()
        if len(text) < min_len:
            continue
        seen.add(href)

        # Etsitään päivämäärä linkin läheltä ja sen puuttuessa osoitteesta.
        # EDPS ja moni muu kirjoittaa päivän polkuun mutta ei korttiin.
        # Jos kumpikaan ei tuota tulosta, käytetään tätä päivää ja
        # merkitään arvaus tagilla näkyviin.
        date, exact = _guess_date(a) or _date_from_url(href), True
        if date is None and detail and resolved < max_detail:
            resolved += 1
            try:
                date = _label_date(
                    _read_capped(sess, href, max_bytes),
                    ("datePublished", "article:published_time", "dateTime"),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("%s: %s ei auennut (%s)", source["id"], href, exc)
        if date is None:
            date, exact = dt.date.today(), False

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                court=source.get("court", source["name"]),
                title=text[:200],
                url=href,
                date=date,
                weight=source.get("weight", 1),
                tags=[] if exact else ["pvm arvioitu"],
            )
        )
    return items


DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


URL_DATE_RE = re.compile(r"/(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[-/]|$)")


def _date_from_url(url: str) -> dt.date | None:
    """Poimii päivämäärän osoitteesta, esim. .../opinions/2026-08-11-eurojust."""
    m = URL_DATE_RE.search(url)
    if not m:
        return None
    try:
        return _sane_date(dt.date(int(m[1]), int(m[2]), int(m[3])))
    except ValueError:
        return None


def _sane_date(date: dt.date | None) -> dt.date | None:
    """Hylkää päivämäärän joka ei voi olla julkaisupäivä.

    Listasivulla on muitakin lukuja kuin julkaisupäiviä. Sisäministeriön
    sivulta poimittiin näin kerran päivä 4.3.2028, joka olisi noussut
    feedin kärkeen ja pysynyt siellä puolitoista vuotta.
    """
    if date is None:
        return None
    today = dt.date.today()
    if date > today or date < today - dt.timedelta(days=5 * 365):
        return None
    return date


def _guess_date(anchor) -> dt.date | None:
    node = anchor
    for _ in range(4):
        if node is None:
            break
        time_el = node.find("time") if hasattr(node, "find") else None
        if time_el and time_el.get("datetime"):
            try:
                found = _sane_date(dt.date.fromisoformat(time_el["datetime"][:10]))
                if found:
                    return found
            except ValueError:
                pass
        m = DATE_RE.search(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else None
        if m:
            d, mo, y = (int(x) for x in m.groups())
            try:
                found = _sane_date(dt.date(y, mo, d))
                if found:
                    return found
            except ValueError:
                pass
        node = node.parent
    return None


_SOFT_HYPHEN_RE = re.compile("[\xad\u200b]")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_card_text(text: str) -> str:
    """Siivoaa tuomioistuimet.fi:n korttien pehmeät tavuviivat ja kapeat välit.

    Sivusto lisää rivitystä varten näkymättömiä merkkejä sanojen sisään
    (esim. "Poh\xadjois-Suo\xadmen" ja "1285/\u200b2026"), jotka eivät näy
    selaimessa mutta tulisivat mukaan tekstiin sellaisenaan.
    """
    return _WHITESPACE_RE.sub(" ", _SOFT_HYPHEN_RE.sub("", text)).strip()


# --------------------------------------------------------------------------
# Tuomioistuimet.fi: hallinto-oikeuksien ja hovioikeuksien ratkaisulistat
# --------------------------------------------------------------------------
# Nämä ovat eri sivuja kuin "tuomioistuimet"-lähteen ajankohtaissyöte: siinä
# on tiedotteita kaikista oikeusasteista, tässä oikeita ratkaisuselosteita
# yhdeltä oikeusasteelta kerrallaan. Sivu näyttää jokaisen ratkaisun
# korttina (div.content-lift), jossa on oma <time datetime="pp.kk.vvvv">,
# asian tunniste otsikkona ja tuomioistuimen itsensä antama asiasanaluettelo
# lyhyenä tiivistelmänä. Asiasanat ovat huomattavasti tarkempia kuin
# ajankohtaissyötteen otsikot (esim. "Tietosuoja – Asiakirjajulkisuus –
# Asiakastietolaki"), joten ne riittävät sellaisenaan keywords-kentäksi ja
# avainsanasuodatus toimii niiden varassa hyvin. Sivu listaa satoja
# ratkaisuja kaikista aihepiireistä, joten lähteellä ei ole always_include-
# eikä require_any-asetusta: pelkkä yleinen must_any-suodatus riittää.
def fetch_court_rulings(source: dict) -> list[Item]:
    soup = BeautifulSoup(_get(source).text, "html.parser")
    card_selector = source.get("card_selector", "div.content-lift")

    seen: set[str] = set()
    items: list[Item] = []
    for card in soup.select(card_selector):
        a = card.find("a", href=True)
        if a is None:
            continue
        href = urllib.parse.urljoin(source["url"], a["href"].strip())
        if href in seen:
            continue

        title_el = card.find(class_="content-lift__title")
        if title_el is None:
            continue
        title = _clean_card_text(title_el.get_text(" ", strip=True))
        if not title:
            continue

        date, exact = None, True
        time_el = card.find("time")
        if time_el is not None:
            m = DATE_RE.search(time_el.get("datetime", "") or time_el.get_text(" ", strip=True))
            if m:
                d, mo, y = (int(x) for x in m.groups())
                try:
                    date = _sane_date(dt.date(y, mo, d))
                except ValueError:
                    date = None
        if date is None:
            date = _date_from_url(href)
        if date is None:
            date, exact = dt.date.today(), False

        excerpt_el = card.find(class_="content-lift__excerpt")
        keywords = _clean_card_text(excerpt_el.get_text(" ", strip=True)) if excerpt_el else ""

        seen.add(href)
        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                court=source.get("court", source["name"]),
                title=title[:220],
                url=href,
                date=date,
                keywords=keywords[:300],
                weight=source.get("weight", 1),
                tags=[] if exact else ["pvm arvioitu"],
            )
        )
    return items


# --------------------------------------------------------------------------
# Finlex: säädöskokoelma ja hallituksen esitykset
# --------------------------------------------------------------------------
# Finlexillä ei ole avointa rajapintaa. api.finlex.fi vastaa 401 ja
# opendata.finlex.fi 403, joten tiedot on luettava listasivun HTML:stä.
# Sivusto on Next.js ja lista tulee palvelinkomponenttien virtana, joten
# valmista DOM-listaa ei ole. Otsikot löytyvät kuitenkin linkkien
# aria-label-arvoista muodossa "853/2026, Valtioneuvoston asetus ...".
#
# Listasivulla ei ole päivämääriä, ja niitä on vuoden mittaan yli 800.
# Siksi ensin suodatetaan otsikon perusteella ja vasta sitten haetaan
# julkaisupäivä yksittäisten säädösten sivuilta. Näin verkkopyyntöjä
# tulee kymmeniä eikä satoja.
_FINLEX_ITEM = re.compile(
    r'aria-label\\?":\\?"(\d+)/(\d{4}),\s*([^"\\]{3,300}?)\\?"'
    r'.{0,600}?href\\?":\\?"(/fi/[^"\\]{5,90})\\?"',
    re.S,
)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _label_date(body: str, labels: tuple[str, ...]) -> dt.date | None:
    """Poimii päivämäärän yksittäisen jutun sivulta.

    Sivun rakennetta ei kannata yrittää hahmottaa säännöllisellä
    lausekkeella, koska Next.js pakkaa JSONin kahteen kertaan lainausmerkein
    ja kenoviivoin. Riittää etsiä otsikkosana ja sen jäljestä ensimmäinen
    ISO-päivämäärä. Nimiöt annetaan tärkeysjärjestyksessä, joten Finlexillä
    julkaisupäivä voittaa antopäivän ja IAPP:lla julkaisupäivä voittaa
    muokkauspäivän.
    """
    for label in labels:
        start = 0
        while True:
            idx = body.find(label, start)
            if idx < 0:
                break
            m = _ISO_DATE.search(body, idx, idx + 400)
            if m:
                return _sane_date(dt.date(int(m[1]), int(m[2]), int(m[3])))
            start = idx + len(label)
    return None


def _read_capped(sess: requests.Session, url: str, max_bytes: int) -> str:
    """Lukee sivusta enintään max_bytes tavua.

    Hallituksen esityksen sivu on parhaimmillaan yli kaksi megatavua, koska
    koko esityksen teksti tulee samassa vastauksessa. Metatiedot ovat
    alkupäässä, joten loppua ei tarvitse ladata.
    """
    resp = sess.get(url, timeout=TIMEOUT, stream=True)
    resp.raise_for_status()
    chunks, total = [], 0
    for chunk in resp.iter_content(chunk_size=65536):
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            break
    resp.close()
    return b"".join(chunks).decode("utf-8", errors="replace")


def fetch_finlex(source: dict) -> list[Item]:
    lookback = int(source.get("lookback_days", 60))
    cutoff = dt.date.today() - dt.timedelta(days=lookback)
    max_detail = int(source.get("max_detail", 25))
    max_bytes = int(source.get("max_bytes", 900_000))
    require = [t.lower() for t in source.get("require_any") or []]

    sess = _session(source)
    listing = _get(source).text

    # Listasivun yläreunassa on nostoja ajantasaisesta lainsäädännöstä.
    # Ne osoittavat polkuun /fi/lainsaadanto/2026/812 eivätkä saman
    # säädöksen säädöskokoelmasivulle, joten sama säädös tulisi feediin
    # kahtena eri osoitteena. Rajataan haku lähteen omaan osastoon.
    section = urllib.parse.urlparse(source["url"]).path.rsplit("/", 1)[0] + "/"

    # Sama säädös esiintyy sivulla useaan kertaan. Pidetään numerojärjestys
    # ja pudotetaan toistot, koska numero kasvaa julkaisujärjestyksessä.
    seen: set[str] = set()
    candidates: list[tuple[int, str, str]] = []
    for number, year, title, href in _FINLEX_ITEM.findall(listing):
        if not href.startswith(section) or not href.endswith(f"/{year}/{number}"):
            continue
        url = urllib.parse.urljoin(source["url"], href)
        if url in seen:
            continue
        seen.add(url)
        full = f"{number}/{year}, {title.strip()}"
        candidates.append((int(number), full, url))

    candidates.sort(key=lambda c: -c[0])

    # Esisuodatus otsikosta ennen kuin yhtään yksittäistä sivua haetaan.
    if require:
        candidates = [c for c in candidates if any(t in c[1].lower() for t in require)]

    items: list[Item] = []
    misses = 0
    for _, title, url in candidates[:max_detail]:
        try:
            body = _read_capped(sess, url, max_bytes)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: %s ei auennut (%s)", source["id"], url, exc)
            continue

        date = _label_date(body, ("Julkaisup", "Antop"))
        if date is None:
            continue
        if date < cutoff:
            # Numerot kasvavat ajan mukana, joten vanhoja tulee vain lisää.
            misses += 1
            if misses >= 3:
                break
            continue

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                court=source.get("court", source["name"]),
                title=title[:220],
                url=url,
                date=date,
                weight=source.get("weight", 1),
            )
        )
    return items


# --------------------------------------------------------------------------
# OAI-PMH: yliopistojen julkaisuarkistot (väitöskirjat, gradut)
# --------------------------------------------------------------------------
# DSpace-arkistot puhuvat OAI-PMH:ta. ListRecords palauttaa 100 tietuetta
# kerrallaan ja antaa resumptionTokenin seuraavaa sivua varten. Tietueet
# tulevat datestamp-järjestyksessä vanhimmasta uusimpaan, joten haku pitää
# aloittaa tarpeeksi läheltä nykyhetkeä eikä sivuja kannata hakea rajatta.
def fetch_oai_pmh(source: dict) -> list[Item]:
    lookback = int(source.get("lookback_days", 75))
    since = (dt.date.today() - dt.timedelta(days=lookback)).isoformat()
    max_pages = int(source.get("max_pages", 6))

    sess = _session()
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc", "from": since}
    if source.get("oai_set"):
        params["set"] = source["oai_set"]

    items: list[Item] = []
    for _ in range(max_pages):
        resp = sess.get(source["url"], params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")

        error = soup.find("error")
        if error is not None:
            # noRecordsMatch on normaali tilanne, ei virhe.
            if error.get("code") != "noRecordsMatch":
                log.warning("%s OAI-virhe: %s", source["id"], error.get("code"))
            break

        for record in soup.find_all("record"):
            item = _oai_item(record, source)
            if item is not None:
                items.append(item)

        token = soup.find("resumptionToken")
        value = token.get_text(strip=True) if token else ""
        if not value:
            break
        params = {"verb": "ListRecords", "resumptionToken": value}

    return items


def _oai_item(record, source: dict) -> Item | None:
    meta = record.find("metadata")
    if meta is None:
        return None

    def values(tag: str) -> list[str]:
        return [e.get_text(" ", strip=True) for e in meta.find_all(tag)]

    titles = values("dc:title")
    if not titles:
        return None

    # Handle-osoite on pysyvä, muut identifierit voivat olla tiedostopolkuja.
    ids = values("dc:identifier")
    url = next((i for i in ids if i.startswith("http") and "handle" in i), "")
    url = url or next((i for i in ids if i.startswith("http")), "")
    if not url:
        return None

    # Julkaisupäivä on dc:date. Jos se ei jäsenny, käytetään tietueen
    # muokkausaikaa headerista.
    header = record.find("header")
    stamp = header.find("datestamp").get_text(strip=True) if header and header.find("datestamp") else ""
    date = None
    for candidate in values("dc:date") + [stamp]:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", candidate)
        if m:
            parsed = dt.date(int(m[1]), int(m[2]), int(m[3]))
            if parsed <= dt.date.today():
                date = parsed
                break
    if date is None:
        return None

    # Tyyppirajaus pudottaa arkistojen muun aineiston (kuvat, aineistot) pois.
    wanted = [t.lower() for t in source.get("type_contains") or []]
    if wanted:
        types = " ".join(values("dc:type")).lower()
        if not any(w in types for w in wanted):
            return None

    return Item(
        source_id=source["id"],
        source_name=source["name"],
        court=source.get("court", source["name"]),
        title=titles[0][:220],
        url=url,
        date=date,
        keywords=", ".join(values("dc:subject"))[:300],
        summary=" ".join(values("dc:description"))[:400],
        weight=source.get("weight", 1),
    )


FETCHERS = {
    "wp_rss": fetch_wp_rss,
    "plain_rss": fetch_plain_rss,
    "eu_sparql": fetch_eu_sparql,
    "html_list": fetch_html_list,
    "oai_pmh": fetch_oai_pmh,
    "finlex": fetch_finlex,
    "court_rulings": fetch_court_rulings,
}


@dataclass
class SourceResult:
    """Yhden lähteen ajon lopputulos.

    Tätä tarvitaan sivun lähdepaneeliin. Pelkkä juttulista ei riitä, koska
    nolla juttua voi tarkoittaa kahta eri asiaa: lähde vastasi eikä sillä
    ollut mitään uutta, tai lähde ei vastannut lainkaan. Nämä pitää erottaa
    toisistaan, jotta sivulla voi luvata että se kertoo mitä ei ole katettu.
    """

    source_id: str
    name: str
    court: str
    items: list[Item] = field(default_factory=list)
    ok: bool = True
    optional: bool = False
    error: str = ""


def fetch_source(source: dict) -> SourceResult:
    """Hakee yhden lähteen. Virhe ei kaada koko ajoa."""
    result = SourceResult(
        source_id=source["id"],
        name=source.get("name", source["id"]),
        court=source.get("court", source["id"]),
        optional=bool(source.get("optional")),
    )

    fetcher = FETCHERS.get(source["type"])
    if fetcher is None:
        log.warning("Tuntematon lähdetyyppi %r lähteessä %s", source["type"], source["id"])
        result.ok = False
        result.error = f"tuntematon lähdetyyppi {source['type']}"
        return result
    try:
        items = fetcher(source)

        # Lähdekohtainen lisäehto. Julkaisuarkistot sisältävät kaiken alan
        # tutkimuksen, joten niistä otetaan vain oikeustieteellinen aineisto.
        # Tämä on eri asia kuin sources.yaml:n aihekohtainen must_any.
        require = [t.lower() for t in source.get("require_any") or []]
        if require:
            items = [i for i in items if any(t in i.haystack() for t in require)]

        # Lähdekohtainen poissulku. Globaali never-lista ei sovi tähän, koska
        # sama sana voi olla toisessa lähteessä juuri se mitä haetaan.
        # Esimerkki: "kriittinen haavoittuvuus" on Kyberturvallisuuskeskuksen
        # tuotetiedotteissa pelkkää kohinaa, mutta sama sana komission
        # tiedotteessa koskee kyberkestävyyssäädöstä.
        block = [t.lower() for t in source.get("never_any") or []]
        if block:
            items = [i for i in items
                     if not any(t in i.title_haystack() for t in block)]

        # Osa lähteistä (esim. tuomioistuinlaitoksen yhteinen ajankohtaissyöte)
        # kattaa monta eri oikeusastetta yhdellä feedillä, ja sources.yaml:n
        # "court" on silloin vain yleisnimi. court_patterns antaa poimia
        # todellisen oikeusasteen otsikosta, jotta sivun oikeusaste-suodatin
        # näyttää esim. "Hallinto-oikeus" eikä pelkkää yleisnimeä.
        #
        # Jokainen sääntö on {match: [sana1, sana2, ...], label: "..."}, ja
        # KAIKKIEN match-sanojen pitää löytyä otsikosta (ei riitä yksi).
        # Tämä tarvitaan, koska esim. "korkein hallinto-oikeus" pitää
        # tunnistaa omaksi KHO:kseen eikä pudota yleiseen "Hallinto-oikeus"
        # -koriin: "korkein"-sana taipuu (korkein/korkeimman/korkeimmassa),
        # joten vartalo "korkei" yhdessä sanan "hallinto-oikeu" kanssa
        # kattaa taivutusmuodot ilman että osuu tavalliseen aluehallinto-
        # oikeuteen. Säännöt tarkistetaan järjestyksessä ja ensimmäinen
        # osuma voittaa, joten tarkin sääntö kirjoitetaan ensin.
        patterns = source.get("court_patterns") or []
        if patterns:
            for item in items:
                low = item.title.lower()
                for rule in patterns:
                    needles = rule.get("match") or []
                    if needles and all(n in low for n in needles):
                        item.court = rule.get("label", item.court)
                        break

        if source.get("always_include"):
            for item in items:
                item.always = True
        log.info("%-12s %3d juttua", source["id"], len(items))
        result.items = items
        return result
    except Exception as exc:  # noqa: BLE001
        level = logging.WARNING if source.get("optional") else logging.ERROR
        log.log(level, "%-12s epäonnistui: %s", source["id"], exc)
        result.ok = False
        result.error = str(exc)[:200]
        return result
