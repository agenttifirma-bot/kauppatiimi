"""Saantopohjainen vertailusalkku ilman kielimallia (tehtava 2026-11-01-39).
Strategiat: trendinseuranta (hinta > N pv liukuva keskiarvo), volatiliteettiin perustuvat (kaanteinen volatiliteetti) painot ja niiden yhdistelma.
Vertailut: BTC osta ja pida sekä tasainen kuukausiosto (DCA). Sama universumi (point-in-time), sama kulumalli (rajat.KULU, rajat.SLIPPAGE)
ja sama simulaattori (backtest._aja -> salkku.suorita_paiva, riskirajat mukana) kuin muilla strategioilla.
Ei parametrihakua: parametrit on kiinteitty etukateen (100 pv, 30 pv, 7 pv), joten ei ruudukkoa eika monivertailukorjausta,
mutta myos ei todistetta robustisuudesta. Ei kosketa lukittuun loppujaksoon (backtest.aja kieltaytyy). Puhdasta koodia, ei LLM:aa."""
import statistics
from datetime import date, datetime, timedelta, timezone

import backtest as bt
import mittarit as mit
import rajat

PV = 86400000


def _painot(valitut, osuus, voltit=None):
    """Tasapaino tai kaanteinen volatiliteetti. Summa osuus, yksittaisen ylaraja rajat.MAX_POSITIO (ylijaama jaa kateiseksi)."""
    if not valitut:
        return {}
    if voltit is None:
        raaka = {s: 1.0 for s in valitut}
    else:
        raaka = {s: 1.0 / voltit[s] for s in valitut}
    summa = sum(raaka.values())
    return {s: min(osuus * v / summa, rajat.MAX_POSITIO) for s, v in raaka.items()}


def _vol(c):
    tuotot = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    return statistics.stdev(tuotot) if len(tuotot) > 1 else 0.0


def _tehdas(tila_fn, osuus, reb):
    def tehdas():
        tila = {"n": 0, "paino": {}}

        def strat(data, paiva, sallitut):
            if tila["n"] % reb == 0:
                tila["paino"] = tila_fn(data, _ms(paiva), sallitut, osuus)
            tila["n"] += 1
            # kolikko pois universumista -> ei mainita -> myydaan (muuten simulaattori hylkaa koko ehdotuksen)
            return {s: w for s, w in tila["paino"].items() if s in sallitut}
        return strat
    return tehdas


def _ms(p):
    return bt._ms(p)


def trendi(ikkuna=100, osuus=0.8, reb=7):
    """Tasapainoin ne universumin kolikot, joiden edellisen paivan sulku on yli viime `ikkuna` sulun keskiarvon."""
    def f(data, d_ms, sallitut, osuus):
        valitut = []
        for s in sorted(sallitut):
            c = data.sulut(s, d_ms, ikkuna)
            if c and c[-1] > sum(c) / len(c):
                valitut.append(s)
        return _painot(valitut, osuus)
    return _tehdas(f, osuus, reb)


def voltti(ikkuna=30, osuus=0.8, reb=7):
    """Kaikki universumin kolikot, paino kaanteisesti viime `ikkuna` paivan paivatuottojen keskihajonnan mukaan."""
    def f(data, d_ms, sallitut, osuus):
        voltit = {}
        for s in sorted(sallitut):
            c = data.sulut(s, d_ms, ikkuna + 1)
            if c:
                v = _vol(c)
                if v > 0:
                    voltit[s] = v
        return _painot(sorted(voltit), osuus, voltit)
    return _tehdas(f, osuus, reb)


def trendi_voltti(trendi_ikkuna=100, vol_ikkuna=30, osuus=0.8, reb=7):
    """Trendisuodatin (hinta > keskiarvo) + kaanteinen volatiliteettipaino vain suodattimen lapaisseille."""
    def f(data, d_ms, sallitut, osuus):
        voltit = {}
        for s in sorted(sallitut):
            c = data.sulut(s, d_ms, trendi_ikkuna)
            v = data.sulut(s, d_ms, vol_ikkuna + 1)
            if c and v and c[-1] > sum(c) / len(c) and _vol(v) > 0:
                voltit[s] = _vol(v)
        return _painot(sorted(voltit), osuus, voltit)
    return _tehdas(f, osuus, reb)


# ---------- vertailut (samat kulut, ei riskirajoja: puhdas vertailu) ----------

def _kuukausialut(alku, loppu):
    p, ulos = alku, []
    while p <= loppu:
        if p == alku or p.day == 1:
            ulos.append(p)
        p += timedelta(days=1)
    return ulos


def btc_osta_pida(data, alku, loppu, osuus=0.8, symbol="BTCUSDT", alkupaoma=None):
    """Osuus alkupaomasta BTC:hen alkupaivan avaushintaan (kulu + slippage), loput kateiseksi. Arvot: alkupaoma + paivan sulut."""
    pao = float(alkupaoma if alkupaoma is not None else rajat.ALKUPAOMA)
    o, c = data.open[symbol], data.close[symbol]
    kulutus = pao * osuus
    q = kulutus / (o[_ms(alku)] * (1 + rajat.SLIPPAGE) * (1 + rajat.KULU))
    arvot, p = [pao], alku
    while p <= loppu:
        arvot.append(pao - kulutus + q * c[_ms(p)])
        p += timedelta(days=1)
    return arvot


def dca(data, alku, loppu, osuus=0.8, symbol="BTCUSDT", alkupaoma=None):
    """Tasainen kuukausiosto: osuus alkupaomasta jaetaan tasan kuukausiin (osto kunkin kuun 1. paivana, ensimmainen alkupaivana)
    avaushintaan kulun ja slippagen kanssa. Ostamaton osa on kateista."""
    pao = float(alkupaoma if alkupaoma is not None else rajat.ALKUPAOMA)
    o, c = data.open[symbol], data.close[symbol]
    ostopaivat = set(_kuukausialut(alku, loppu))
    era = pao * osuus / len(ostopaivat)
    kassa, q, arvot, p = pao, 0.0, [pao], alku
    while p <= loppu:
        if p in ostopaivat:
            q += era / (o[_ms(p)] * (1 + rajat.SLIPPAGE) * (1 + rajat.KULU))
            kassa -= era
        arvot.append(kassa + q * c[_ms(p)])
        p += timedelta(days=1)
    return arvot


# ---------- ajo ----------

def strategiat():
    return {"trendi100": trendi(100), "voltti30": voltti(30), "trendi100+voltti30": trendi_voltti(100, 30)}


def ikkunat_90(alku, loppu, pituus=90):
    ulos, p = [], alku
    while p + timedelta(days=pituus - 1) <= loppu:
        ulos.append((p, p + timedelta(days=pituus - 1)))
        p += timedelta(days=pituus)
    return ulos


def vertaile(data, alku, loppu, osuus=0.8):
    """Palauttaa {'jatkuva': {nimi: {mittarit, kauppoja}}, 'ikkunat90': {...}}.
    jatkuva: yksi salkku koko jakson (hatajarru 25 % voi lukita kassaan pysyvasti, kuten oikeassa paperikaupassa).
    ikkunat90: tuore salkku joka 90 pv jaksolle, tuotot ketjutettu (jarru nollautuu; samaan tapaan kuin walk-forward)."""
    if loppu >= bt.holdout_alku():
        raise bt.Holdoutvirhe("saantosalkku ei saa ulottua lukittuun jaksoon")
    jat, ikk = {}, {}
    for nimi, th in strategiat().items():
        arvot, n = bt._aja(th, data, alku, loppu)
        jat[nimi] = {"mittarit": mit.mittarit(arvot), "kauppoja": n}
        osat, nyht = [], 0
        for a, b in ikkunat_90(alku, loppu):
            ar, nn = bt._aja(th, data, a, b)
            osat.append(ar)
            nyht += nn
        ikk[nimi] = {"mittarit": mit.mittarit(bt._ketju(osat)), "kauppoja": nyht}
    jat["btc_osta_pida"] = {"mittarit": mit.mittarit(btc_osta_pida(data, alku, loppu, osuus)), "kauppoja": 1}
    jat["dca_kuukausi"] = {"mittarit": mit.mittarit(dca(data, alku, loppu, osuus)), "kauppoja": len(_kuukausialut(alku, loppu))}
    osat = [btc_osta_pida(data, a, b, osuus) for a, b in ikkunat_90(alku, loppu)]
    ikk["btc_osta_pida"] = {"mittarit": mit.mittarit(bt._ketju(osat)), "kauppoja": len(osat)}
    return {"jatkuva": jat, "ikkunat90": ikk}


def taulukko(tulos):
    f = lambda x: "n/a" if x is None else "%.1f %%" % (x * 100)
    rivit = []
    for otsikko, avain in (("Jatkuva (yksi salkku, hatajarru voimassa)", "jatkuva"), ("90 pv ikkunat ketjutettuna (jarru nollautuu)", "ikkunat90")):
        rivit += ["", otsikko, "| Salkku | Tuotto | Max DD | Vol/v | Sharpe/v | Kauppoja |", "|---|---|---|---|---|---|"]
        for nimi, r in tulos[avain].items():
            m = r["mittarit"] or {}
            sh = m.get("sharpe_pa")
            rivit.append("| %s | %s | %s | %s | %s | %d |" % (nimi, f(m.get("tuotto")), f(m.get("max_dd")), f(m.get("vol_pa")),
                                                         "n/a" if sh is None else "%.2f" % sh, r["kauppoja"]))
    return "\n".join(rivit)


def main():
    import argparse
    import laaja
    ap = argparse.ArgumentParser(description="Saantosalkku vs BTC vs DCA (ei koske holdoutiin)")
    ap.add_argument("--osuus", type=float, default=0.8)
    args = ap.parse_args()
    try:
        data = laaja.rehellinen_data()
    except laaja.HistoriaPuuttuu as e:
        print(e)
        return 2
    alku, loppu = date(*rajat.BACKTEST_ALKU), bt.holdout_alku() - timedelta(days=1)
    print("Jakso %s .. %s, osuus %.0f %%, kulu %.2f %% + slippage %.2f %% per kauppa" % (
        alku, loppu, args.osuus * 100, rajat.KULU * 100, rajat.SLIPPAGE * 100))
    print(taulukko(vertaile(data, alku, loppu, args.osuus)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
