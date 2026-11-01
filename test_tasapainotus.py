"""Koe 1 (tasapainotus.py): oletus pois, N paivan valein, riskivahdin myynnit toimivat, salkku.py koskematon."""
import unittest
from datetime import timedelta

import rajat
import salkku
import tasapainotus as tp
from test_k3 import ALKU, S, markkina


def ajo(ehdotukset, n, hinnat=None, alkupaoma=10000.0):
    pv = len(ehdotukset) + 2
    mk = markkina(hinnat or {s: [(100, 100)] * pv for s in S})
    con = salkku.avaa(":memory:", alkupaoma=alkupaoma)
    ulos = []
    for i, e in enumerate(ehdotukset):
        p = ALKU + timedelta(days=i)
        e = tp.suodata(con, mk, p, e, S, n)
        ulos.append(salkku.suorita_paiva(con, mk, p, e, S))
    return ulos


class TasapainotusTesti(unittest.TestCase):
    def test_oletus_pois(self):
        self.assertEqual(tp.lue_ymparisto({}), 0)
        self.assertEqual(tp.lue_ymparisto({"KAUPPA_REB_PV": "7"}), 0)          # ilman PAALLA-lippua ei mitaan
        self.assertEqual(tp.lue_ymparisto({"KAUPPA_REB_PAALLA": "0", "KAUPPA_REB_PV": "7"}), 0)
        e = {"BTCUSDT": 0.1}
        self.assertIs(tp.suodata(None, None, ALKU, e, S), e)                    # ymparistomuuttujat puuttuvat -> ennallaan

    def test_ymparisto(self):
        self.assertEqual(tp.lue_ymparisto({"KAUPPA_REB_PAALLA": "1"}), 7)       # oletus 7
        for arvo, odotus in (("3", 3), (" 14 ", 14), ("1", 0), ("0", 0), ("31", 0), ("-2", 0), ("abc", 0), ("7.5", 0), ("", 0)):
            self.assertEqual(tp.lue_ymparisto({"KAUPPA_REB_PAALLA": "1", "KAUPPA_REB_PV": arvo}), odotus, arvo)

    def test_n1_ennallaan(self):
        e = {"BTCUSDT": 0.1}
        self.assertIs(tp.suodata(None, None, ALKU, e, S, 1), e)
        self.assertIs(tp.suodata(None, None, ALKU, e, S, 0), e)

    def test_ensimmainen_paiva_ja_nvalein(self):
        # joka paiva eri ehdotus: n=3 -> kauppaa vain paivina 0, 3, 6
        ehd = [{"BTCUSDT": 0.10}, {"BTCUSDT": 0.12}, {"BTCUSDT": 0.14}, {"BTCUSDT": 0.05}, {"BTCUSDT": 0.12}, {"BTCUSDT": 0.14}, {"ETHUSDT": 0.10}]
        t = ajo(ehd, 3)
        kauppapaivat = [i for i, x in enumerate(t) if x["kaupat"]]
        self.assertEqual(kauppapaivat, [0, 3, 6])

    def test_ei_tasapainopaivana_ei_ostoja_eika_harkinnanvaraisia_myyntteja(self):
        t = ajo([{"BTCUSDT": 0.10}, {"BTCUSDT": 0.0, "ETHUSDT": 0.10}, None, {}], 7)
        self.assertEqual([x["kaupat"] for x in t[1:]], [[], [], []])

    def test_ilman_suodatinta_kauppaa_joka_paiva(self):
        t = ajo([{"BTCUSDT": 0.10}, {"BTCUSDT": 0.0}], 1)
        self.assertTrue(t[1]["kaupat"])

    def test_riskivahdin_myynti_toimii_ei_tasapainopaivana(self):
        # BTC nousee: paino ylittaa MAX_POSITIO -> salkku myy ylimaaran vaikka ei ole tasapainopaiva
        pv = 6
        hinnat = {"BTCUSDT": [(100, 100), (100, 100), (200, 200), (200, 200), (200, 200), (200, 200)],
                  "ETHUSDT": [(100, 100)] * pv, "SOLUSDT": [(100, 100)] * pv}
        t = ajo([{"BTCUSDT": rajat.MAX_POSITIO}] * 4, 7, hinnat)
        myynnit = [k for x in t[1:] for k in x["kaupat"] if k[2] == "SELL"]
        self.assertTrue(myynnit, "ylipainon myynti puuttuu")

    def test_hatajarru_toimii_ei_tasapainopaivana(self):
        pv = 8
        pudotus = [(100, 100)] * 3 + [(40, 40)] * (pv - 3)   # kaikki -60 % -> salkku -27 % > MAX_DRAWDOWN
        hinnat = {s: pudotus for s in S}
        t = ajo([{"BTCUSDT": rajat.MAX_POSITIO, "ETHUSDT": rajat.MAX_POSITIO, "SOLUSDT": rajat.MAX_POSITIO}] * 6, 30, hinnat)
        self.assertTrue(any(x["jarru"] for x in t))

    def test_puuttuva_hinta_ehdotus_ennallaan(self):
        mk = markkina({s: [(100, 100)] * 4 for s in S})
        con = salkku.avaa(":memory:", alkupaoma=10000.0)
        salkku.suorita_paiva(con, mk, ALKU, {"BTCUSDT": 0.10}, S)
        e = {"BTCUSDT": 0.12}
        # paiva ALKU+20 on datan ulkopuolella ja ei tasapainopaiva (20 % 7 != 0)
        self.assertIs(tp.suodata(con, mk, ALKU + timedelta(days=20), e, S, 7), e)


if __name__ == "__main__":
    unittest.main()
