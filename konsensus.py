"""Konsensussaanto: kauppa tehdaan vain, jos flash ja pro ehdottavat SAMAA suuntaa (osta lisaa / myy) samalle kolikolle samana paivana.
Muuten kolikon paino pysyy ennallaan. Kun molemmat ovat samaa mielta, muutos on varovaisempi (pienempi) kahdesta.
Suodatin ENNEN salkkua (kuten kynnys.py): salkku.py, riskivahti.py ja rajat.py ovat koskemattomia, salkku siivoaa tuloksen omilla rajoillaan.
OLETUS POIS: toimii vain jos KAUPPA_KONSENSUS=1. Toisen mallin ehdotus luetaan sen salkun paatokset-taulusta (vain luku).
Fail closed: toisen mallin ehdotus puuttuu / hylatty / virheellinen -> ei kauppoja (nykypainot)."""
import json
import os
import sqlite3

import rajat
import riskivahti
import salkku
import kynnys

TOLERANSSI = 0.005   # alle 0,5 %-yks. ero nykypainoon = "pida" (sama kuin rajat.MIN_KAUPPA_OSUUS)


def kaytossa(env=None):
    return (os.environ if env is None else env).get("KAUPPA_KONSENSUS") == "1"


def suunta(tavoite, nyky, tol=TOLERANSSI):
    d = tavoite - nyky
    return 1 if d > tol else (-1 if d < -tol else 0)


def yhdista(nyky, a, b, tol=TOLERANSSI):
    """nyky, a, b: {symbol: paino}. Palauttaa tavoitepainot. Puuttuva symboli ehdotuksessa = tavoite 0 (myy)."""
    ulos = {}
    for s in sorted(set(nyky) | set(a) | set(b)):
        c, ta, tb = nyky.get(s, 0.0), a.get(s, 0.0), b.get(s, 0.0)
        sa, sb = suunta(ta, c, tol), suunta(tb, c, tol)
        if sa == sb == 1:
            t = c + min(ta - c, tb - c)     # osta vain se, mihin molemmat yltavat
        elif sa == sb == -1:
            t = c + max(ta - c, tb - c)     # myy vain se, minka molemmat myisivat
        else:
            t = c                           # erimielisyys tai ei muutosta -> pida
        if t > 1e-12:
            ulos[s] = t
    return ulos


def lue_ehdotus(polku, paiva):
    """Toisen mallin salkun paivan ehdotus (dict) tai None jos puuttuu / hylatty / ei dict. Vain luku, ei koskaan nosta poikkeusta."""
    if not polku or not os.path.exists(polku):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % polku, uri=True, timeout=10)
        try:
            r = con.execute("SELECT ehdotus, hylatty FROM paatokset WHERE paiva=?", (paiva.isoformat(),)).fetchone()
        finally:
            con.close()
        if r is None or r[1]:
            return None
        e = json.loads(r[0])
    except (sqlite3.Error, TypeError, ValueError):
        return None
    return e if isinstance(e, dict) else None


def nykypainot(con, markkina, paiva):
    """Salkun painot paivan avaushinnoilla (kuten kynnys.py). Hinta puuttuu -> None."""
    omat = salkku.positiot(con)
    hinnat = kynnys._avaushinnat(markkina, paiva, set(omat))
    if hinnat is None:
        return None
    v = salkku.kateinen(con) + sum(omat[s] * hinnat[s] for s in omat)
    return {s: omat[s] * hinnat[s] / v for s in omat} if v > 0 else {}


def suodata(con, markkina, paiva, oma, toinen, sallitut, paalla=None):
    """oma: oman mallin ehdotus, toinen: toisen mallin ehdotus (dict tai None). Pois paalta -> oma sellaisenaan.
    Paalla: palauttaa konsensuspainot; mika tahansa epavarmuus -> nykypainot (ei kauppoja)."""
    if not (kaytossa() if paalla is None else paalla):
        return oma
    nyky = nykypainot(con, markkina, paiva)
    if nyky is None:
        return oma   # hinta puuttuu: salkku kasittelee tilanteen omilla saannoillaan (Datavirhe omistetulle)
    try:
        a, _ = riskivahti.siisti_ehdotus(oma, sallitut)
        b, _ = riskivahti.siisti_ehdotus(toinen, sallitut)
    except riskivahti.Ehdotusvirhe:
        return dict(nyky)   # ehdotus puuttuu tai on virheellinen -> ei kauppoja
    uusi = yhdista(nyky, a, b)
    if sum(uusi.values()) > 1.0 - rajat.KATEISPUSKURI_MIN:
        return dict(nyky)
    return uusi
