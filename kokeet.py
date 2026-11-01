"""Paperikokeiden yhteinen apuri (backtest ilman kielimallia). Vain luku: ei kosketa salkku.py:hyn, riskivahtiin, rajat.py:hyn eika holdoutiin.
- aja_kuluilla: sama simulaattori ja kulut kuin backtest._aja, mutta palauttaa myos kulut (USDT) ja hyvaksyy suodattimia.
- btc_osta_pida / dca_btc: passiiviset vertailut samoilla kuluilla (KULU + SLIPPAGE).
Holdout-jaksoa ei voi ajaa: Holdoutvirhe, kuten backtest.aja:ssa."""
from datetime import date, datetime, timedelta, timezone

import backtest as bt
import mittarit as mit
import rajat
import salkku
from salkku import Datavirhe

PV = 86400000


def _ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


def _tarkista_jakso(loppu):
    if loppu >= bt.holdout_alku():
        raise bt.Holdoutvirhe("jakso ylittaa lukitun loppujakson (%s alkaen)" % bt.holdout_alku())


def aja_kuluilla(tehdas, data, alku, loppu, suodattimet=()):
    """tehdas: backtest-strategiatehdas. suodattimet: [f(sal, markkina, paiva, ehdotus, sallitut) -> ehdotus], ajetaan jarjestyksessa.
    Palauttaa dict: arvot (alkupaoma mukana), kauppoja, kulut (kulu + slippage, USDT), maksut (vain kulu)."""
    _tarkista_jakso(loppu)
    sal = salkku.avaa(":memory:")
    strat = tehdas()
    nak = bt._Nakyma(data)
    for p in bt._paivat(alku, loppu):
        sallitut = set(data.universum(_ms(p)))
        ehd = strat(nak, p, sallitut)
        for f in suodattimet:
            ehd = f(sal, data.con, p, ehd, sallitut)
        salkku.suorita_paiva(sal, data.con, p, ehd, sallitut)
    arvot = [rajat.ALKUPAOMA] + [r[0] for r in sal.execute("SELECT arvo FROM arvot ORDER BY paiva")]
    kauppoja, maksut, slip = sal.execute("SELECT COUNT(*), COALESCE(SUM(kulu),0), COALESCE(SUM(slippage_kulu),0) FROM kaupat").fetchone()
    sal.close()
    return {"arvot": arvot, "kauppoja": kauppoja, "maksut": maksut, "kulut": maksut + slip}


def btc_osta_pida(data, alku, loppu, osuus=1.0):
    """BTC ostetaan alkupaivan avaushintaan (kulu + slippage), pidetaan loppuun. Loput kateista."""
    _tarkista_jakso(loppu)
    rivit = mit.vertailusalkku(data.con, {"BTCUSDT": osuus}, alku, loppu)
    arvot = [rajat.ALKUPAOMA] + [v for _, v in rivit]
    kulut = rajat.ALKUPAOMA * osuus * (rajat.KULU + rajat.SLIPPAGE) if osuus > 0 else 0.0
    return {"arvot": arvot, "kauppoja": 1, "maksut": rajat.ALKUPAOMA * osuus * rajat.KULU, "kulut": kulut}


def dca_btc(data, alku, loppu, osuus=1.0):
    """Tasainen kuukausiosto: osuus*alkupaoma jaetaan tasan kuukausiin; osto kunkin kuun 1. paivan (tai jakson 1. paivan) avaushintaan.
    Ostamaton osa on kateista (ei korkoa). Kulut kuten salkussa."""
    _tarkista_jakso(loppu)
    paivat = list(bt._paivat(alku, loppu))
    kuukaudet = sorted({(p.year, p.month) for p in paivat})
    osto_paivat = {}
    for p in paivat:
        osto_paivat.setdefault((p.year, p.month), p)   # kuukauden ensimmainen paiva jaksossa
    era = rajat.ALKUPAOMA * osuus / len(kuukaudet)
    close, open_ = data.close["BTCUSDT"], data.open["BTCUSDT"]
    kassa, qty, kulut, maksut, ostoja = rajat.ALKUPAOMA, 0.0, 0.0, 0.0, 0
    ostopvt = set(osto_paivat.values())
    arvot = [rajat.ALKUPAOMA]
    for p in paivat:
        d = _ms(p)
        if p in ostopvt:
            if d not in open_:
                raise Datavirhe("dca: ei avaushintaa %s" % p)
            hinta = open_[d] * (1 + rajat.SLIPPAGE)
            q = era / (hinta * (1 + rajat.KULU))
            maksu = q * hinta * rajat.KULU
            qty += q
            kassa -= era
            maksut += maksu
            kulut += maksu + q * open_[d] * rajat.SLIPPAGE
            ostoja += 1
        if d not in close:
            raise Datavirhe("dca: ei sulkuhintaa %s" % p)
        arvot.append(kassa + qty * close[d])
    return {"arvot": arvot, "kauppoja": ostoja, "maksut": maksut, "kulut": kulut}


def rivi(nimi, r):
    """Taulukkorivi: nimi, tuotto-%, kulut-USDT, kulut-% alkupaomasta, max drawdown-%, kauppoja, Sharpe."""
    m = mit.mittarit(r["arvot"]) or {}
    return {"nimi": nimi, "tuotto": m.get("tuotto"), "kulut": r["kulut"], "kulut_pros": r["kulut"] / rajat.ALKUPAOMA,
            "max_dd": m.get("max_dd"), "kauppoja": r["kauppoja"], "sharpe": m.get("sharpe_pa")}


def taulukko(rivit):
    f = lambda x: "n/a" if x is None else "%+.1f %%" % (x * 100)
    p = lambda x: "n/a" if x is None else "%.1f %%" % (x * 100)
    ulos = ["| Strategia | Tuotto | Kulut (USDT) | Kulut % alkupaomasta | Max drawdown | Kauppoja | Sharpe |",
            "|---|---|---|---|---|---|---|"]
    for r in rivit:
        ulos.append("| %s | %s | %.0f | %.1f %% | %s | %d | %s |" % (
            r["nimi"], f(r["tuotto"]), r["kulut"], r["kulut_pros"] * 100, p(r["max_dd"]), r["kauppoja"],
            "n/a" if r["sharpe"] is None else "%.2f" % r["sharpe"]))
    return "\n".join(ulos)


def jakso():
    """Oletusjakso: BACKTEST_ALKU .. paivaa ennen holdoutia."""
    return date(*rajat.BACKTEST_ALKU), bt.holdout_alku() - timedelta(days=1)
