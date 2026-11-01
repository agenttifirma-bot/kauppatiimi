"""No-trade band (kynnys.py): oletus pois, pienet muutokset ohitetaan, poistuminen ei esty, salkku.py koskematon."""
import os
import unittest
from datetime import timedelta

import kynnys
import salkku
from test_k3 import ALKU, S, markkina


def ajo(ehdotukset, kp):
    mk = markkina({s: [(100, 100)] * 6 for s in S})
    con = salkku.avaa(":memory:", alkupaoma=10000.0)
    ulos = []
    for i, e in enumerate(ehdotukset):
        p = ALKU + timedelta(days=i)
        e = kynnys.suodata(con, mk, p, e, S, kp)
        ulos.append(salkku.suorita_paiva(con, mk, p, e, S))
    return ulos


class KynnysTesti(unittest.TestCase):
    def test_oletus_pois(self):
        self.assertEqual(kynnys.KYNNYS_PP, 0.0)
        e = {"BTCUSDT": 0.108}
        self.assertIs(kynnys.suodata(None, None, ALKU, e, S), e)

    def test_ymparisto_lukeminen(self):
        for arvo, odotus in (("2", 2.0), ("2.5", 2.5), ("0", 0.0), ("-1", 0.0), ("abc", 0.0), ("50", 0.0), ("nan", 0.0)):
            self.assertEqual(kynnys.lue_ymparisto({"KAUPPA_KYNNYS_PP": arvo}), odotus, arvo)
        self.assertEqual(kynnys.lue_ymparisto({}), 0.0)

    def test_ymparisto_ohjaa_suodatusta(self):
        mk = markkina({s: [(100, 100)] * 6 for s in S})
        con = salkku.avaa(":memory:", alkupaoma=10000.0)
        salkku.suorita_paiva(con, mk, ALKU, {"BTCUSDT": 0.10}, S)
        e = {"BTCUSDT": 0.108}
        vanha = os.environ.get("KAUPPA_KYNNYS_PP")
        try:
            os.environ["KAUPPA_KYNNYS_PP"] = "2"
            self.assertNotEqual(kynnys.suodata(con, mk, ALKU + timedelta(days=1), e, S), e)
            os.environ.pop("KAUPPA_KYNNYS_PP")
            self.assertIs(kynnys.suodata(con, mk, ALKU + timedelta(days=1), e, S), e)
        finally:
            if vanha is not None:
                os.environ["KAUPPA_KYNNYS_PP"] = vanha

    def test_nolla_ei_muuta(self):
        e = [{"BTCUSDT": 0.10}, {"BTCUSDT": 0.108}]
        self.assertEqual(len(ajo(e, 0.0)[1]["kaupat"]), 1)

    def test_pieni_muutos_ohitetaan(self):
        t = ajo([{"BTCUSDT": 0.10}, {"BTCUSDT": 0.108}], 2.0)
        self.assertEqual(t[1]["kaupat"], [])

    def test_iso_muutos_menee_lapi(self):
        t = ajo([{"BTCUSDT": 0.10}, {"BTCUSDT": 0.14}], 2.0)
        self.assertEqual(len(t[1]["kaupat"]), 1)

    def test_taysi_poistuminen_ei_esty(self):
        t = ajo([{"BTCUSDT": 0.10}, {}], 5.0)
        self.assertEqual([k[2] for k in t[1]["kaupat"]], ["SELL"])
        t = ajo([{"BTCUSDT": 0.10}, {"BTCUSDT": 0.0}], 5.0)
        self.assertEqual([k[2] for k in t[1]["kaupat"]], ["SELL"])

    def test_pienta_uutta_ei_avata(self):
        t = ajo([{"BTCUSDT": 0.10}, {"BTCUSDT": 0.10, "ETHUSDT": 0.01}], 2.0)
        self.assertEqual(t[1]["kaupat"], [])

    def test_virheellinen_ehdotus_ennallaan(self):
        e = {"XRPUSDT": 0.1}
        self.assertIs(kynnys.suodata(None, None, ALKU, e, S, 2.0), e)
        self.assertIsNone(kynnys.suodata(None, None, ALKU, None, S, 2.0))


if __name__ == "__main__":
    unittest.main()
