"""Suorituskykymittarit ja vertailusalkku (osta ja pida)."""
import math
import statistics
from datetime import date, datetime, timedelta, timezone

import rajat
from salkku import Datavirhe

PV = 86400000


def mittarit(arvot):
    """arvot: paivan paattymisarvot. Palauttaa dict (tuotto, max_dd, vol_pa, sharpe_pa)."""
    if len(arvot) < 3:
        return None
    tuotot = [arvot[i] / arvot[i - 1] - 1 for i in range(1, len(arvot))]
    huippu, mdd = arvot[0], 0.0
    for a in arvot:
        huippu = max(huippu, a)
        mdd = max(mdd, 1 - a / huippu)
    sd = statistics.stdev(tuotot)
    return {
        "tuotto": arvot[-1] / arvot[0] - 1,
        "max_dd": mdd,
        "vol_pa": sd * math.sqrt(365),
        "sharpe_pa": (statistics.fmean(tuotot) / sd * math.sqrt(365)) if sd > 0 else None,
    }


def vertailusalkku(markkina, painot, alku, loppu, alkupaoma=None):
    """Osta ja pida: painot {symbol: osuus} ostetaan alku-paivan avaushintaan (kulu + slippage), loput kateiseksi.
    Palauttaa [(paiva_iso, arvo)] paivan sulkuhinnoilla alku..loppu (molemmat mukana)."""
    pao = float(alkupaoma if alkupaoma is not None else rajat.ALKUPAOMA)
    ms = lambda p: int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)
    kassa = pao
    maarat = {}
    for s, w in painot.items():
        r = markkina.execute("SELECT open FROM hinnat WHERE symbol=? AND ts=?", (s, ms(alku))).fetchone()
        if r is None:
            raise Datavirhe("vertailusalkku: ei avaushintaa %s %s" % (s, alku))
        hinta = r[0] * (1 + rajat.SLIPPAGE)
        kulutus = pao * w
        maarat[s] = kulutus / (hinta * (1 + rajat.KULU))
        kassa -= kulutus
    ulos, p = [], alku
    while p <= loppu:
        arvo = kassa
        for s, q in maarat.items():
            r = markkina.execute("SELECT close FROM hinnat WHERE symbol=? AND ts=?", (s, ms(p))).fetchone()
            if r is None:
                raise Datavirhe("vertailusalkku: ei sulkuhintaa %s %s" % (s, p))
            arvo += q * r[0]
        ulos.append((p.isoformat(), arvo))
        p += timedelta(days=1)
    return ulos


# --- Passiiviset vertailut (paivittainen raportti) ---
DCA_ERIA = 3        # 3 tasaerää kuukauden (30 pv) välein = 90 pv paperijakso (portti 1), loput kateisena odottamassa
DCA_VALI_PV = 30


def _avaus(avaukset, p, loppu):
    """Ensimmainen saatavilla oleva avaushinta paivalta p alkaen (puuttuva paiva siirtaa ostoa), enintaan paivaan loppu asti."""
    while p <= loppu:
        if p in avaukset:
            return avaukset[p]
        p += timedelta(days=1)
    return None


def _sulku(sulut, alku, p):
    """Viimeisin tunnettu sulkuhinta paivaan p asti (puuttuva paiva ei kaada: kaytetaan edellista)."""
    while p >= alku:
        if p in sulut:
            return sulut[p]
        p -= timedelta(days=1)
    return None


def _osto(era, avaushinta):
    """Kuinka paljon ostetaan erilla era (kulu + slippage kuten vertailusalkussa)."""
    return era / (avaushinta * (1 + rajat.SLIPPAGE) * (1 + rajat.KULU))


def passiiviset(avaukset, sulut, alku, paiva, alkupaoma=None):
    """Puhdas funktio (ei verkkoa, ei kirjoitusta): BTC osta ja pida seka DCA paivana `paiva`.
    avaukset/sulut: {date: hinta} (BTC). Alkupaoma ostetaan alku-paivan avaushintaan (osta ja pida: yksi osto;
    DCA: DCA_ERIA tasaerää DCA_VALI_PV paivan valein alku-paivasta). Kulu ja liukuma = rajat.KULU / rajat.SLIPPAGE.
    Palauttaa {"osta_ja_pida": (arvo, tuotto), "dca": (arvo, tuotto)} tai None jos hintoja ei ole lainkaan."""
    pao = float(alkupaoma if alkupaoma is not None else rajat.ALKUPAOMA)
    if paiva < alku:
        return None
    sulku = _sulku(sulut, alku, paiva)
    h0 = _avaus(avaukset, alku, paiva)
    if sulku is None or h0 is None:
        return None
    bh = _osto(pao, h0) * sulku
    kassa, maara = pao, 0.0
    era = pao / DCA_ERIA
    for k in range(DCA_ERIA):
        p = alku + timedelta(days=k * DCA_VALI_PV)
        if p > paiva:
            break
        h = _avaus(avaukset, p, paiva)
        if h is None:
            break    # ostopaivan hintaa ei vielä ole: era odottaa kateisena
        maara += _osto(era, h)
        kassa -= era
    dca = kassa + maara * sulku
    return {"osta_ja_pida": (bh, bh / pao - 1), "dca": (dca, dca / pao - 1)}


def vertailurivi(salkun_tuotto, passiivinen):
    """Yksi raporttirivi: salkun ja passiivisten tuottojen ero prosenttiyksikkoina (+ = salkku voittaa).
    Ei hintoja -> 'ei saatavilla'."""
    if passiivinen is None:
        return "vs. BTC osta ja pida: ei saatavilla, vs. DCA: ei saatavilla"
    return "vs. BTC osta ja pida: %+.2f %%-yks, vs. DCA: %+.2f %%-yks" % (
        100 * (salkun_tuotto - passiivinen["osta_ja_pida"][1]), 100 * (salkun_tuotto - passiivinen["dca"][1]))
