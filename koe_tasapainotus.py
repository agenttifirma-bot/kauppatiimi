"""Koe 1: tasapainotustiheys N = 1, 3, 7, 14 historiadatalla (ei kielimallia; signaali lasketaan joka paiva, tasapainotus vain joka N. paiva).
Ajo: python3 koe_tasapainotus.py --db <markkina.db>   (vain kehitysjakso, holdout lukittu). Vain luku."""
import argparse
import sys

import backtest as bt
import db
import kokeet as kk
import tasapainotus as tp

N_ARVOT = (1, 3, 7, 14)


def aja_koe(data, alku, loppu):
    rivit = []
    for nimi, tehdas in (("momentum90 k5", bt.momentum(ikkuna=90, k=5, osuus=0.8, reb=1)), ("tasapaino 80 %", bt.tasapaino(0.8))):
        for n in N_ARVOT:
            suod = [lambda sal, mk, p, e, s, n=n: tp.suodata(sal, mk, p, e, s, n)]
            rivit.append(kk.rivi("%s, N=%d" % (nimi, n), kk.aja_kuluilla(tehdas, data, alku, loppu, suod)))
    rivit.append(kk.rivi("BTC osta ja pida 100 %", kk.btc_osta_pida(data, alku, loppu, 1.0)))
    rivit.append(kk.rivi("BTC osta ja pida 90 %", kk.btc_osta_pida(data, alku, loppu, 0.9)))
    rivit.append(kk.rivi("BTC DCA kuukausittain 100 %", kk.dca_btc(data, alku, loppu, 1.0)))
    return rivit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    alku, loppu = kk.jakso()
    data = bt.Data(db.avaa(a.db))
    print("Jakso %s .. %s" % (alku, loppu))
    print(kk.taulukko(aja_koe(data, alku, loppu)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
