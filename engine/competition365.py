"""Exact 365Scores competition identity via the *same response's* catalog.

Research adapter for explicitly known 365Scores numeric league identifiers.
Each identifier below was read from a public 365Scores league page URL;
no ID enumeration, no inference from the name of a club or fixture.

The game must supply an unambiguous competitionId. When the response includes
root 'competitions', require the exact ID to have an allowed name and correct
international/domestic type. Missing or conflicting catalog entries FAIL CLOSED.
"""
from __future__ import annotations
import re
import unicodedata

# https://www.365scores.com/football/league/uefa-champions-league-572
# https://www.365scores.com/football/league/liga-portugal-73
# https://www.365scores.com/football/league/super-lig-78
# https://www.365scores.com/it/Voetbal/league/serie-a-17
# https://www.365scores.com/football/league/jupiler-pro-league-98
# https://www.365scores.com/Voetbal/league/premier-league-7
# https://www.365scores.com/football/league/laliga-11
KNOWN = {
    "572": {"league": "uefa.cl", "prefixes": ("Europe", "International"), "names": (
        "UEFA Champions League", "Champions League", "UCL",
        "UEFA Champions League 2026/2027"),
        "international": True},
    "73": {"league": "pt.1", "prefixes": ("Portugal",), "names": (
        "Liga Portugal", "Primeira Liga", "Portuguese Primeira Liga",
        "Liga Portugal Betclic"), "international": False},
    "78": {"league": "tr.1", "prefixes": ("Turkiye", "Turkey"), "names": (
        "Super Lig", "Süper Lig", "Trendyol Super Lig", "Turkish Super Lig"),
        "international": False},
    "17": {"league": "it.1", "prefixes": ("Italy",), "names": (
        "Serie A", "Italian Serie A", "Italy Serie A"), "international": False},
    "7": {"league": "en.1", "prefixes": ("England",), "names": (
        "Premier League", "English Premier League"), "international": False},
    "11": {"league": "es.1", "prefixes": ("Spain",), "names": (
        "LaLiga", "La Liga", "Spanish LaLiga", "Primera Division"),
        "international": False},
    "98": {"league": "be.1", "prefixes": ("Belgium",), "names": (
        "Jupiler Pro League", "Belgium Jupiler Pro League",
        "Belgian Pro League"), "international": False},
}


def canonical(v):
    norm=unicodedata.normalize("NFKD", str(v or "").casefold())
    norm="".join(c for c in norm if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", norm).split())


def raw_id(v):
    if isinstance(v, bool) or v is None:
        return ""
    s=str(v)
    return s if re.fullmatch(r"[1-9][0-9]{0,11}",s) else ""


def _catalog(payload):
    # Some match endpoints return a catalog array at the root, NOT inside game.
    data=payload.get("competitions") if isinstance(payload,dict) else None
    if not isinstance(data,list) or len(data)>1000:
        return None
    return data


def resolve(payload, *, expected_leagues=None):
    """Return verified identity info or a structured rejection reason.

    A catalog matching an ID without matching its official competition name is
    NOT enough: provider may change its ID namespace or response shape.
    This only identifies the competition; it doesn't verify every shot or xG.
    """
    game=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(game,dict):
        return {"ok":False,"reason":"invalid_game"}
    nested=game.get("competition")
    nested=nested if isinstance(nested,dict) else {}
    gid=raw_id(game.get("competitionId") or game.get("competitionDisplayId")
               or nested.get("id") or nested.get("competitionId"))
    if gid not in KNOWN:
        return {"ok":False,"reason":"unknown_competition_id",
                "provider_competition_id":gid}
    spec=KNOWN[gid]
    if expected_leagues is not None and spec["league"] not in expected_leagues:
        return {"ok":False,"reason":"competition_not_requested",
                "provider_competition_id":gid}
    allowed={canonical(x) for x in spec["names"]}
    label=game.get("competitionDisplayName") or game.get("competitionName") or nested.get("name")
    def valid_display(text):
        if canonical(text) in allowed:
            return True
        # 365Scores live game details use "Europe, UEFA Champions League",
        # whereas its embedded catalog uses "UEFA Champions League".
        # Accept ONLY documented region/country + a known exact league name.
        if isinstance(text,str) and "," in text:
            region,competition=text.split(",",1)
            prefixes={canonical(x) for x in spec["prefixes"]}
            return canonical(region) in prefixes and canonical(competition) in allowed
        return False
    if label and not valid_display(label):
        return {"ok":False,"reason":"game_competition_name_disagrees",
                "provider_competition_id":gid}
    cat=_catalog(payload)
    catalog_verified=False
    if cat is not None:
        matches=[c for c in cat if isinstance(c,dict) and raw_id(c.get("id"))==gid]
        if len(matches)!=1:
            return {"ok":False,"reason":"catalog_id_missing_or_duplicate",
                    "provider_competition_id":gid}
        obj=matches[0]
        names=[str(obj.get("name") or ""),str(obj.get("longName") or "")]
        # Name and long name can differ (e.g. "UEFA Champions League" vs
        # "Champions League"); accept EITHER if provider-controlled.
        if not any(canonical(x) in allowed for x in names if x):
            return {"ok":False,"reason":"catalog_name_disagrees",
                    "provider_competition_id":gid}
        if isinstance(obj.get("isInternational"),bool) and obj["isInternational"] != spec["international"]:
            return {"ok":False,"reason":"international_type_disagrees",
                    "provider_competition_id":gid}
        if obj.get("countryId") is None:
            return {"ok":False,"reason":"catalog_country_identity_missing",
                    "provider_competition_id":gid}
        catalog_verified=True
    # Without the catalog, only accept an explicit confirmed name from the
    # game, not the bare numerical ID. The audit retains proof method.
    if not catalog_verified and not valid_display(label):
        return {"ok":False,"reason":"no_catalog_and_no_verified_display_name",
                "provider_competition_id":gid}
    return {"ok":True,"league":spec["league"],
            "provider_competition_id":gid,
            "competition_identity_basis":("id+catalog_name+countryId" if catalog_verified
                                          else "id+game_display_name"),
            "catalog_verified":catalog_verified,
            "international":spec["international"]}

