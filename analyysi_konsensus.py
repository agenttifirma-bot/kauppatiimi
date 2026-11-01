"""Konsensussaannon jalkikateinen toisto toteutuneista flash- ja pro-ehdotuksista (ei uusia LLM-kutsuja, vain luku lahdekannoille).
Ajo: python3 analyysi_konsensus.py --markkina <markkina.db> --flash <salkku_flash.db> --pro <salkku_pro.db>
Toisto ajaa oman muistisalkun (aloitus 10000 USDT) samoilla kuluilla ja salkku.suorita_paiva:lla. Kirjoittaa vain stdoutiin.
HUOM: otos on lyhyt (forward-paperikauppa, ~17 pv), tulos on suuntaa antava, ei tilastollinen todiste. Ei sovitettavia parametreja."""
import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timezone

import backtest as bt
import db
import konsensus as ks
import mittarit as mit
import rajat
import salkku


def _ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


def _ro(polku):
    return sqlite3.connect("file:%s?mode=ro" % polku, uri=True, timeout=10)


def omat_tulokset(polku):
    c = _ro(polku)
    arvot = [rajat.ALKUPAOMA] + [r[0] for r in c.execute("SELECT arvo FROM arvot ORDER BY paiva")]
    kaupat = c.execute("SELECT paiva, symbol, puoli, maara*hinta, kulu+slippage_kulu FROM kaupat ORDER BY id").fetchall()
    c.close()
    return {"arvot": arvot, "kaupat": kaupat}


def toisto(markkina, flash, pro):
    data = bt.Data(markkina)
    c = _ro(flash)
    paivat = [date.fromisoformat(r[0]) for r in c.execute("SELECT paiva FROM paatokset ORDER BY paiva")]
    c.close()
    sal = salkku.avaa(":memory:")
    tilasto = {"kolikkopaivia_ehdotus": 0, "sama_suunta": 0, "vastakkain": 0, "toinen_pitaa": 0, "ehdotus_puuttuu_paivia": 0}
    for p in paivat:
        a, b = ks.lue_ehdotus(flash, p), ks.lue_ehdotus(pro, p)
        nyky = ks.nykypainot(sal, markkina, p) or {}
        sallitut = set(data.universum(_ms(p)))
        if isinstance(a, dict) and isinstance(b, dict):
            sallitut |= set(a) | set(b)
            for s in set(nyky) | set(a) | set(b):
                sa, sb = ks.suunta(a.get(s, 0.0), nyky.get(s, 0.0)), ks.suunta(b.get(s, 0.0), nyky.get(s, 0.0))
                if sa == sb == 0:
                    continue
                tilasto["kolikkopaivia_ehdotus"] += 1
                tilasto["sama_suunta" if sa == sb else ("toinen_pitaa" if 0 in (sa, sb) else "vastakkain")] += 1
            ehd = ks.suodata(sal, markkina, p, a, b, sallitut, True)
        else:
            tilasto["ehdotus_puuttuu_paivia"] += 1
            ehd = None   # fail closed: ei kauppoja
        salkku.suorita_paiva(sal, markkina, p, ehd, sallitut)
    arvot = [rajat.ALKUPAOMA] + [r[0] for r in sal.execute("SELECT arvo FROM arvot ORDER BY paiva")]
    kaupat = sal.execute("SELECT paiva, symbol, puoli, maara*hinta, kulu+slippage_kulu FROM kaupat ORDER BY id").fetchall()
    return paivat, {"arvot": arvot, "kaupat": kaupat}, tilasto


def rivi(nimi, r):
    m = mit.mittarit(r["arvot"]) or {}
    kulut = sum(k[4] for k in r["kaupat"])
    return {"nimi": nimi, "loppu": r["arvot"][-1], "tuotto": m.get("tuotto"), "kulut": kulut, "max_dd": m.get("max_dd"),
            "kauppoja": len(r["kaupat"]), "sharpe": m.get("sharpe_pa")}


def taulukko(rivit):
    f = lambda x, k: "n/a" if x is None else k % x
    ulos = ["| Strategia | Loppuarvo (USDT) | Tuotto | Kulut (USDT) | Max drawdown | Kauppoja | Sharpe |", "|---|---|---|---|---|---|---|"]
    for r in rivit:
        ulos.append("| %s | %.0f | %s | %.1f | %s | %d | %s |" % (
            r["nimi"], r["loppu"], f(None if r["tuotto"] is None else r["tuotto"] * 100, "%+.2f %%"), r["kulut"],
            f(None if r["max_dd"] is None else r["max_dd"] * 100, "%.2f %%"), r["kauppoja"], f(r["sharpe"], "%.2f")))
    return "\n".join(ulos)


def poisjaaneet(omat, konsensus):
    """Oman mallin kaupat, joille ei ole vastinetta (sama paiva, kolikko, puoli) konsensustoistossa. Karkea arvio, ei tarkka kontrafaktuaali:
    salkut etenevat eri poluilla, joten positiot ja kaupan koko eroavat."""
    on = {(k[0], k[1], k[2]) for k in konsensus["kaupat"]}
    pois = [k for k in omat["kaupat"] if (k[0], k[1], k[2]) not in on]
    return len(pois), sum(k[4] for k in pois)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markkina", required=True)
    ap.add_argument("--flash", required=True)
    ap.add_argument("--pro", required=True)
    a = ap.parse_args()
    markkina = db.avaa(a.markkina)
    paivat, k, tilasto = toisto(markkina, a.flash, a.pro)
    fl, pr = omat_tulokset(a.flash), omat_tulokset(a.pro)
    print("Jakso %s .. %s (%d pv)" % (paivat[0], paivat[-1], len(paivat)))
    print("Kolikkopaivat, joissa ainakin toinen malli ehdotti muutosta: %s" % json.dumps(tilasto))
    b = mit.vertailusalkku(markkina, {"BTCUSDT": 1.0}, paivat[0], paivat[-1])
    btc = {"arvot": [rajat.ALKUPAOMA] + [v for _, v in b],
           "kaupat": [(paivat[0].isoformat(), "BTCUSDT", "osto", rajat.ALKUPAOMA, rajat.ALKUPAOMA * (rajat.KULU + rajat.SLIPPAGE))]}
    print(taulukko([rivi("flash (toteutunut)", fl), rivi("pro (toteutunut)", pr), rivi("konsensus flash+pro (toisto)", k),
                    rivi("BTC osta ja pida", btc)]))
    for nimi, o in (("flash", fl), ("pro", pr)):
        n, kulu = poisjaaneet(o, k)
        print("%s: %d / %d kauppaa ilman vastinetta konsensustoistossa, niiden kulut %.1f USDT (karkea arvio)" % (nimi, n, len(o["kaupat"]), kulu))
    return 0


if __name__ == "__main__":
    sys.exit(main())
