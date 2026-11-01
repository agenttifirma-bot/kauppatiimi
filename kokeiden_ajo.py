"""Kokeiden yhteisajo oikealla hintahistorialla (tehtava 71). Vain luku: lahdetiedostot avataan immutable=1-tilassa, joten
SQLite ei luo lukko- tai WAL-tiedostoja (hakemisto on vain luku). Holdout on lukittu (kk.jakso() paattyy paivaa ennen holdoutia).
Ajo: KAUPPA_HISTORIA_DB=<historia.db> python3 kokeiden_ajo.py --markkina <markkina.db> --flash <salkku_flash.db> --pro <salkku_pro.db>
Ei kielimallikutsuja, ei parametrihakua: kaikki parametrit ovat kiinteita (saantosalkku.py, koe_tasapainotus.py)."""
import argparse
import sqlite3
import sys

_alkup_connect = sqlite3.connect


def _vain_luku(polku, *a, **kw):
    if isinstance(polku, str) and polku.startswith("/") and not polku.startswith("file:"):
        return _alkup_connect("file:%s?immutable=1" % polku, uri=True, timeout=10)
    return _alkup_connect(polku, *a, **kw)


sqlite3.connect = _vain_luku

import backtest as bt  # noqa: E402
import db  # noqa: E402
import kokeet as kk  # noqa: E402
import koe_tasapainotus as kt  # noqa: E402
import laaja  # noqa: E402
import analyysi_konsensus as ak  # noqa: E402
import saantosalkku as ss  # noqa: E402

_avaa_alkup = db.avaa


def _avaa(polku):
    return _avaa_alkup(polku) if polku == ":memory:" else sqlite3.connect(polku)


db.avaa = _avaa


def _ketju_rivi(nimi, osat):
    """osat: [kk-tulos]. Ketjuttaa arvot, summaa kulut ja kaupat."""
    return kk.rivi(nimi, {"arvot": bt._ketju([o["arvot"] for o in osat]), "kauppoja": sum(o["kauppoja"] for o in osat),
                          "kulut": sum(o["kulut"] for o in osat)})


def saanto_ja_vertailut(data, alku, loppu, osuus=0.8):
    jat, ikk = [], []
    ikkunat = ss.ikkunat_90(alku, loppu)
    for nimi, th in ss.strategiat().items():
        jat.append(kk.rivi(nimi, kk.aja_kuluilla(th, data, alku, loppu)))
        ikk.append(_ketju_rivi(nimi, [kk.aja_kuluilla(th, data, a, b) for a, b in ikkunat]))
    for o in (osuus, 1.0):
        jat.append(kk.rivi("BTC osta ja pida %d %%" % (o * 100), kk.btc_osta_pida(data, alku, loppu, o)))
        jat.append(kk.rivi("BTC DCA kuukausi %d %%" % (o * 100), kk.dca_btc(data, alku, loppu, o)))
        ikk.append(_ketju_rivi("BTC osta ja pida %d %%" % (o * 100), [kk.btc_osta_pida(data, a, b, o) for a, b in ikkunat]))
        ikk.append(_ketju_rivi("BTC DCA kuukausi %d %%" % (o * 100), [kk.dca_btc(data, a, b, o) for a, b in ikkunat]))
    return jat, ikk, len(ikkunat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markkina", required=True)
    ap.add_argument("--flash", required=True)
    ap.add_argument("--pro", required=True)
    a = ap.parse_args()
    data = laaja.rehellinen_data()
    alku, loppu = kk.jakso()
    print("Jakso %s .. %s (holdout %s alkaen lukittu), data: historia.db (point-in-time-universumi, delistaukset mukana)" % (alku, loppu, bt.holdout_alku()))
    jat, ikk, n = saanto_ja_vertailut(data, alku, loppu)
    print("\n## 1. Saantosalkku, jatkuva jakso\n" + kk.taulukko(jat))
    print("\n## 1b. Saantosalkku, %d kpl 90 pv ikkunoita ketjutettuna (jarru nollautuu)\n" % n + kk.taulukko(ikk))
    print("\n## 2a. Tasapainotuskoe N = 1, 3, 7, 14 (jatkuva jakso)\n" + kk.taulukko(kt.aja_koe(data, alku, loppu)))
    markkina = db.avaa(a.markkina)
    paivat, k, tilasto = ak.toisto(markkina, a.flash, a.pro)
    fl, pr = ak.omat_tulokset(a.flash), ak.omat_tulokset(a.pro)
    print("\n## 2b. Konsensuksen jalkitoisto %s .. %s (%d pv)\nKolikkopaivat: %s" % (paivat[0], paivat[-1], len(paivat), tilasto))
    b = ak.mit.vertailusalkku(markkina, {"BTCUSDT": 1.0}, paivat[0], paivat[-1])
    btc = {"arvot": [ak.rajat.ALKUPAOMA] + [v for _, v in b],
           "kaupat": [(paivat[0].isoformat(), "BTCUSDT", "osto", ak.rajat.ALKUPAOMA, ak.rajat.ALKUPAOMA * (ak.rajat.KULU + ak.rajat.SLIPPAGE))]}
    print(ak.taulukko([ak.rivi("flash (toteutunut)", fl), ak.rivi("pro (toteutunut)", pr), ak.rivi("konsensus (toisto)", k),
                       ak.rivi("BTC osta ja pida", btc)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
