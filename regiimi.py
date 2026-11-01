"""Regiimitunnistus ja regiimiportti K7-strategioille (vain tutkimus, paperilla).
Saannot (kaikki kayttavat vain dataa ENNEN paivaa d, ei tulevaisuutta; kiinteat etukateen, ei sovitettu):
 - trendi:  BTC sulku >= BTC:n 200 pv keskiarvo
 - vola:    BTC:n 30 pv realisoitunut vaihtelu <= sen oma viimeisen 365 pv mediaani (matala vola)
 - molemmat: trendi JA vola
Portti: regiimin ulkopuolella strategia on kateisessa ({}); sisaan tullessa se jatkaa omaa rebalanssiaan.
Ei kosketa rajat.py:hyn, salkku.py:hyn eika holdoutiin (backtest._aja kieltaytyy lukitusta jaksosta).
Ajo: python3 regiimi.py --markkina PATH --kokeilut PATH   (lukee kokeilut-kannan K7-hypoteesit, tulostaa taulukon)"""
import argparse
import json
import sqlite3
import statistics
import sys
from datetime import date, timedelta

import backtest as bt
import k7
import mittarit as mit
import rajat

SAANNOT = ("trendi", "vola", "molemmat")


def _btc(data, d_ms, n):
    return data.sulut("BTCUSDT", d_ms, n)


def trendi_paalla(data, d_ms, sma=200):
    c = _btc(data, d_ms, sma)
    return bool(c) and c[-1] >= sum(c) / len(c)       # data puuttuu -> pois (fail closed)


def _vola(c):
    r = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    return statistics.pstdev(r)


def vola_matala(data, d_ms, lyhyt=30, pitka=365):
    """Nykyinen 30 pv vola <= viimeisen 365 pv rullaavien 30 pv volojen mediaani. Puuttuva data -> False."""
    c = _btc(data, d_ms, pitka + lyhyt)
    if not c:
        return False
    nyt = _vola(c[-(lyhyt + 1):])
    vanhat = [_vola(c[i:i + lyhyt + 1]) for i in range(0, len(c) - lyhyt, 7)]
    return nyt <= statistics.median(vanhat)


def regiimi_paalla(saanto, data, d_ms):
    if saanto == "trendi":
        return trendi_paalla(data, d_ms)
    if saanto == "vola":
        return vola_matala(data, d_ms)
    if saanto == "molemmat":
        return trendi_paalla(data, d_ms) and vola_matala(data, d_ms)
    raise ValueError("tuntematon saanto")


def portti(tehdas, saanto):
    """Kaare strategiatehdas regiimiportilla. Sisainen strategia ajetaan joka paiva (sen tila etenee), mutta tulos
    kaytetaan vain kun regiimi on paalla; muuten kateinen."""
    def uusi():
        inner = tehdas()

        def strat(data, paiva, sallitut):
            ehd = inner(data, paiva, sallitut)
            return ehd if regiimi_paalla(saanto, data, bt._ms(paiva)) else {}
        return strat
    return uusi


def regiimiosuus(data, alku, loppu, saanto):
    p, paalla, yht = alku, 0, 0
    while p <= loppu:
        paalla += 1 if regiimi_paalla(saanto, data, bt._ms(p)) else 0
        yht += 1
        p += timedelta(days=1)
    return paalla / yht if yht else None


def _ketju_testit(tehdas_per_ikkuna, data, ikkunat_):
    osat = [bt._aja(t, data, a, b)[0] for t, (a, b) in zip(tehdas_per_ikkuna, ikkunat_)]
    return bt._ketju(osat)


def vertaa(spec, data):
    """Yksi K7-hypoteesi: walk-forward (valinta vain opetusjaksolla) ja sama valinta regiimiportilla. Palauttaa dict."""
    rek = bt.avaa_rekisteri(":memory:")
    kiint = spec["kiinteat"]
    wf = bt.walk_forward(spec["nimi"], lambda **g: k7.rakenna({**kiint, **g}), k7.ruudukko_lista(spec), data, rek)
    ik = wf["ikkunat"]
    par = [{**kiint, **f["valittu"]} for f in wf["foldit"]]
    ulos = {"nimi": spec["nimi"], "ikkunat": ik, "ilman": wf["mittarit"], "arvot_ilman": wf["arvot"], "ylisovitus": bt.ylisovitus(wf)}
    for s in SAANNOT:
        arv = _ketju_testit([portti(k7.rakenna(p), s) for p in par], data, ik)
        ulos[s] = {"mittarit": mit.mittarit(arv), "arvot": arv}
    return ulos


def btc_portti(data, ik, saanto, osuus):
    """BTC-aikoitus: osuus BTC:ta kun regiimi on paalla, muuten kateinen. Paivatuotto = sulku(d)/sulku(d-1)-1, paatos vain
    dataa ennen paivaa d. Kulu+slippage (rajat) per vaihdettu osuus. Ei kayta salkku.py:ta (se rajaa 15 % per kolikko)."""
    kulu = rajat.KULU + rajat.SLIPPAGE
    osat = []
    for a, b in ik:
        arvo, pos, arvot, p = rajat.ALKUPAOMA, 0.0, [rajat.ALKUPAOMA], a
        while p <= b:
            d_ms = bt._ms(p)
            uusi = osuus if regiimi_paalla(saanto, data, d_ms) else 0.0
            arvo -= arvo * abs(uusi - pos) * kulu
            pos = uusi
            c = data.close["BTCUSDT"]
            arvo *= 1 + pos * (c[d_ms] / c[d_ms - bt.PV] - 1)
            arvot.append(arvo)
            p += timedelta(days=1)
        osat.append(arvot)
    return bt._ketju(osat)


def passiiviset(data, ik):
    """Vertailut samoilla testi-ikkunoilla ja samoilla kuluilla. BTC osta-ja-pida = sama laskenta kuin K7:n btc_vertailu
    (mittarit.vertailusalkku, ei 15 % positiorajaa). BTC + portti: btc_portti."""
    ulos = {}
    for nimi, osuus in (("BTC 80 % osta-ja-pida", 0.8), ("BTC 100 % osta-ja-pida", 1.0)):
        osat = [[v for _, v in mit.vertailusalkku(data.con, {"BTCUSDT": osuus}, a, b)] for a, b in ik]
        ulos[nimi] = mit.mittarit(bt._ketju([[rajat.ALKUPAOMA] + o for o in osat]))
    for s in SAANNOT:
        ulos["BTC 80 %% + %s" % s] = mit.mittarit(btc_portti(data, ik, s, 0.8))
    ulos["kateinen"] = {"tuotto": 0.0, "sharpe_pa": None, "max_dd": 0.0}
    return ulos


def _f(x, p=1):
    return "n/a" if x is None else "%.*f" % (p, x * 100)


def _s(x):
    return "n/a" if x is None else "%.2f" % x


def main(argv=None):
    ap = argparse.ArgumentParser(description="Regiimiportin vertailu K7-strategioille (walk-forward, paperilla)")
    ap.add_argument("--markkina", required=True)
    ap.add_argument("--kokeilut", required=True)
    ap.add_argument("--json", help="kirjoita tulokset tahan")
    a = ap.parse_args(argv)
    data = bt.Data(sqlite3.connect("file:%s?mode=ro" % a.markkina, uri=True))
    kk = sqlite3.connect("file:%s?mode=ro" % a.kokeilut, uri=True)
    specit = []
    for nimi, spec in kk.execute("SELECT nimi, spec FROM k7_hypoteesit ORDER BY id"):
        s = json.loads(spec)
        s.setdefault("nimi", nimi)
        specit.append(s)
    tulokset = []
    for s in specit:
        try:
            t = vertaa(s, data)
        except Exception as e:      # vain tyyppi
            print("virhe %s: %s" % (s.get("nimi"), type(e).__name__), file=sys.stderr)
            continue
        tulokset.append(t)
        print("valmis", t["nimi"], flush=True)
    if not tulokset:
        print("ei tuloksia")
        return 1
    ik = tulokset[0]["ikkunat"]
    print("\nTesti-ikkunat (%d kpl, vain ennen holdoutia %s): %s .. %s" % (len(ik), bt.holdout_alku(), ik[0][0], ik[-1][1]))
    print("\n| Strategia / vertailu | tuotto % | Sharpe | max dd % | opetus-S | testi-S |")
    print("|---|---|---|---|---|---|")
    for t in tulokset:
        y = t["ylisovitus"]
        for tunn, m in (("", t["ilman"]), (" + trendi", t["trendi"]["mittarit"]), (" + vola", t["vola"]["mittarit"]),
                        (" + molemmat", t["molemmat"]["mittarit"])):
            m = m or {}
            ex = ("%s | %s" % (_s(y["train_sharpe"]), _s(y["oos_sharpe"]))) if tunn == "" else " | "
            print("| %s%s | %s | %s | %s | %s |" % (t["nimi"][:34], tunn, _f(m.get("tuotto")), _s(m.get("sharpe_pa")), _f(m.get("max_dd")), ex))
    print("\nPassiiviset vertailut samoilla ikkunoilla:")
    print("| Vertailu | tuotto % | Sharpe | max dd % |\n|---|---|---|---|")
    for n, m in passiiviset(data, ik).items():
        print("| %s | %s | %s | %s |" % (n, _f(m.get("tuotto")), _s(m.get("sharpe_pa")), _f(m.get("max_dd"))))
    print("\nRegiimi paalla (osuus paivista testi-ikkunoissa):")
    for s in SAANNOT:
        yht = [regiimiosuus(data, x, y, s) for x, y in ik]
        print("  %s: %.0f %%" % (s, 100 * sum(yht) / len(yht)))
    if a.json:
        with open(a.json, "w") as f:
            json.dump([{k: v for k, v in t.items() if not k.startswith("arvot")} for t in tulokset], f, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
