"""Konsensussuodatin (konsensus.py): oletus pois, vain sama suunta -> kauppa, fail closed, salkku.py koskematon."""
import os
import sqlite3
import tempfile
import unittest
from datetime import timedelta

import konsensus as ks
import salkku
from test_k3 import ALKU, S, markkina


class YhdistaTesti(unittest.TestCase):
    def test_molemmat_ostavat_pienempi_voittaa(self):
        self.assertAlmostEqual(ks.yhdista({}, {"BTCUSDT": 0.10}, {"BTCUSDT": 0.06})["BTCUSDT"], 0.06)

    def test_vastakkaiset_pitaa(self):
        u = ks.yhdista({"BTCUSDT": 0.05}, {"BTCUSDT": 0.10}, {"BTCUSDT": 0.0})
        self.assertAlmostEqual(u["BTCUSDT"], 0.05)

    def test_toinen_pitaa_ei_kauppaa(self):
        u = ks.yhdista({"BTCUSDT": 0.05}, {"BTCUSDT": 0.10}, {"BTCUSDT": 0.052})
        self.assertAlmostEqual(u["BTCUSDT"], 0.05)

    def test_molemmat_myyvat_vahemman_voittaa(self):
        u = ks.yhdista({"BTCUSDT": 0.10}, {"BTCUSDT": 0.02}, {"BTCUSDT": 0.06})
        self.assertAlmostEqual(u["BTCUSDT"], 0.06)

    def test_molemmat_poistavat(self):
        self.assertNotIn("BTCUSDT", ks.yhdista({"BTCUSDT": 0.10}, {}, {}))

    def test_uusi_kolikko_vain_jos_molemmat(self):
        self.assertEqual(ks.yhdista({}, {"ETHUSDT": 0.1}, {}), {})


class SuodataTesti(unittest.TestCase):
    def setUp(self):
        self.mk = markkina({s: [(100, 100)] * 4 for s in S})
        self.con = salkku.avaa(":memory:", alkupaoma=10000.0)

    def test_oletus_pois(self):
        self.assertFalse(ks.kaytossa({}))
        self.assertFalse(ks.kaytossa({"KAUPPA_KONSENSUS": "0"}))
        self.assertTrue(ks.kaytossa({"KAUPPA_KONSENSUS": "1"}))
        e = {"BTCUSDT": 0.1}
        self.assertIs(ks.suodata(self.con, self.mk, ALKU, e, {"BTCUSDT": 0.0}, S, False), e)

    def test_ei_kauppaa_ilman_yhteista_suuntaa(self):
        t = salkku.suorita_paiva(self.con, self.mk, ALKU, ks.suodata(self.con, self.mk, ALKU, {"BTCUSDT": 0.1}, {"ETHUSDT": 0.1}, S, True), S)
        self.assertEqual(t["kaupat"], [])

    def test_kauppa_kun_molemmat_ostavat(self):
        ehd = ks.suodata(self.con, self.mk, ALKU, {"BTCUSDT": 0.10}, {"BTCUSDT": 0.08}, S, True)
        t = salkku.suorita_paiva(self.con, self.mk, ALKU, ehd, S)
        self.assertEqual([k[1] for k in t["kaupat"]], ["BTCUSDT"])

    def test_toinen_puuttuu_tai_virheellinen_pitaa(self):
        for toinen in (None, {"XYZUSDT": 0.1}, {"BTCUSDT": -1}):
            ehd = ks.suodata(self.con, self.mk, ALKU, {"BTCUSDT": 0.1}, toinen, S, True)
            self.assertEqual(ehd, {})

    def test_oma_puuttuu_pitaa(self):
        self.assertEqual(ks.suodata(self.con, self.mk, ALKU, None, {"BTCUSDT": 0.1}, S, True), {})

    def test_pitaa_olemassa_olevan_position(self):
        salkku.suorita_paiva(self.con, self.mk, ALKU, {"BTCUSDT": 0.1}, S)
        p = ALKU + timedelta(days=1)
        ehd = ks.suodata(self.con, self.mk, p, {"BTCUSDT": 0.0}, {"BTCUSDT": 0.1}, S, True)
        self.assertGreater(ehd.get("BTCUSDT", 0), 0.09)


class LueEhdotusTesti(unittest.TestCase):
    def _kanta(self, rivi):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "s.db")
        c = salkku.avaa(p)
        if rivi:
            c.execute("INSERT INTO paatokset VALUES (?,?,?,?)", rivi)
            c.commit()
        c.close()
        return p

    def test_lukee_ehdotuksen(self):
        p = self._kanta((ALKU.isoformat(), '{"BTCUSDT": 0.1}', "[]", None))
        self.assertEqual(ks.lue_ehdotus(p, ALKU), {"BTCUSDT": 0.1})

    def test_hylatty_null_puuttuu_tiedosto_roska(self):
        self.assertIsNone(ks.lue_ehdotus(self._kanta((ALKU.isoformat(), "null", "[]", "x")), ALKU))
        self.assertIsNone(ks.lue_ehdotus(self._kanta((ALKU.isoformat(), "null", "[]", None)), ALKU))
        self.assertIsNone(ks.lue_ehdotus(self._kanta((ALKU.isoformat(), "{rikki", "[]", None)), ALKU))
        self.assertIsNone(ks.lue_ehdotus(self._kanta(None), ALKU))
        self.assertIsNone(ks.lue_ehdotus("/ei/ole/olemassa.db", ALKU))
        self.assertIsNone(ks.lue_ehdotus(None, ALKU))

    def test_vain_luku(self):
        p = self._kanta((ALKU.isoformat(), '{"BTCUSDT": 0.1}', "[]", None))
        ks.lue_ehdotus(p, ALKU)
        c = sqlite3.connect(p)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM paatokset").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
