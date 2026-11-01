"""Koe 1: tasapainotustiheys. Salkku tasapainotetaan vain joka N. paiva; muina paivina pidetaan nykyiset painot
(riskivahdin myynnit tapahtuvat silti: salkku.py rajaa positiot MAX_POSITIO:on ja kateispuskuriin, ja hatajarru toimii ennallaan).
Suodatus tehdaan ENNEN salkkua: salkku.py, riskivahti.py ja rajat.py ovat koskemattomia. Vain lukeminen.

OLETUS POIS (= tasapainotus joka paiva): paalle vain ymparistomuuttujalla KAUPPA_TASAPAINOTUS_PV=N (sallittu 2..30;
puuttuva tai virheellinen arvo -> koe pois paalta). Suositeltu kokeiluarvo 7. Vain Tony asettaa muuttujan (systemd-ymparisto)."""
import os
from datetime import date, datetime, timezone

import salkku

REB_MIN, REB_MAX = 2, 30


def lue_ymparisto(env=None):
    """Palauttaa N (2..30) jos KAUPPA_TASAPAINOTUS_PV on kelvollinen, muuten 0 (pois = joka paiva)."""
    env = os.environ if env is None else env
    try:
        n = int(str(env.get("KAUPPA_TASAPAINOTUS_PV", "")).strip())
    except (TypeError, ValueError):
        return 0
    return n if REB_MIN <= n <= REB_MAX else 0


def _aloituspaiva(con):
    r = con.execute("SELECT MIN(paiva) FROM arvot").fetchone()
    return r[0] if r else None


def on_tasapainopaiva(con, paiva, n):
    """Ensimmainen ajopaiva on aina tasapainopaiva; sen jalkeen joka n. paiva (kalenteripaivia)."""
    alku = _aloituspaiva(con)
    if alku is None:
        return True
    return (paiva - date.fromisoformat(alku)).days % n == 0


def suodata(con, markkina, paiva, ehdotus, sallitut, n=None):
    """Tasapainopaivana ehdotus sellaisenaan. Muina paivina nykyiset painot (ei uusia ostoja, ei harkinnanvaraisia myynteja);
    salkku.suorita_paiva rajaa ne silti MAX_POSITIO:on ja kateispuskuriin (= riskivahdin myynnit).
    n=None -> ymparistomuuttujat; n<2 -> pois. Puuttuva hinta -> ehdotus ennallaan."""
    n = lue_ymparisto() if n is None else n
    if n < REB_MIN or on_tasapainopaiva(con, paiva, n):
        return ehdotus
    omat = salkku.positiot(con)
    if not omat:
        return {}
    d_ms = _ms(paiva)
    hinnat = {}
    for s in omat:
        h = salkku._hinnat(markkina, s, d_ms)
        if h is None:
            return ehdotus
        hinnat[s] = h[0]
    v = salkku.kateinen(con) + sum(omat[s] * hinnat[s] for s in omat)
    if v <= 0:
        return ehdotus
    return {s: omat[s] * hinnat[s] / v for s in omat}


def _ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)
