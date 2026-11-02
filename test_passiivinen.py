import unittest
from datetime import date, timedelta

import db
import mittarit
import paiva
import rajat

A = date(2026, 10, 15)
K = (1 + rajat.SLIPPAGE) * (1 + rajat.KULU)


def sarja(n, avaus=lambda i: 100.0, sulku=lambda i: 100.0, puuttuu=()):
    av = {A + timedelta(days=i): avaus(i) for i in range(n) if i not in puuttuu}
    su = {A + timedelta(days=i): sulku(i) for i in range(n) if i not in puuttuu}
    return av, su


class PassiivisetTesti(unittest.TestCase):
    def test_vakiohinta_tappio_on_pelkat_kulut(self):
        av, su = sarja(5)
        r = mittarit.passiiviset(av, su, A, A + timedelta(days=4), 10000.0)
        self.assertAlmostEqual(r["osta_ja_pida"][0], 10000.0 / K, 6)
        self.assertAlmostEqual(r["osta_ja_pida"][1], 1 / K - 1, 9)
        self.assertAlmostEqual(r["dca"][1], (1 / K - 1) / 3, 9)    # vain 1. era ostettu, kulut vain sille

    def test_tuplaantuva_hinta_kulut_vahennetty(self):
        av, su = sarja(95, avaus=lambda i: 100.0, sulku=lambda i: 200.0)
        r = mittarit.passiiviset(av, su, A, A + timedelta(days=94), 10000.0)
        self.assertAlmostEqual(r["osta_ja_pida"][0], 10000.0 / K * 2, 6)
        self.assertAlmostEqual(r["dca"][0], 10000.0 / K * 2, 6)   # kaikki 3 erää ostettu samaan hintaan
        self.assertLess(r["osta_ja_pida"][0], 20000.0)

    def test_dca_erat_30_paivan_valein(self):
        # hinta 100 paivat 0-29, 50 paivasta 30 alkaen (avaus ja sulku)
        av, su = sarja(95, avaus=lambda i: 100.0 if i < 30 else 50.0, sulku=lambda i: 100.0 if i < 30 else 50.0)
        r = mittarit.passiiviset(av, su, A, A + timedelta(days=60), 9000.0)
        odotettu = 3000.0 / K / 100 * 50 + 2 * 3000.0 / K
        self.assertAlmostEqual(r["dca"][0], odotettu, 6)
        r29 = mittarit.passiiviset(av, su, A, A + timedelta(days=29), 9000.0)
        self.assertAlmostEqual(r29["dca"][0], 6000.0 + 3000.0 / K, 6)

    def test_puuttuva_paiva_ei_kaada(self):
        av, su = sarja(40, puuttuu=(3, 30, 39))
        r = mittarit.passiiviset(av, su, A, A + timedelta(days=39), 9000.0)   # loppupaivan hinta puuttuu -> edellinen sulku
        self.assertIsNotNone(r["osta_ja_pida"])
        self.assertAlmostEqual(r["dca"][0], 3000.0 + 2 * 3000.0 / K, 6)   # era 2 ostettu 31.-paivan avaukseen (ostopaiva 30 puuttui)

    def test_alkupaivan_hinta_puuttuu_siirtaa_ostoa(self):
        av, su = sarja(3, avaus=lambda i: 100.0 * (i + 1), sulku=lambda i: 100.0 * (i + 1), puuttuu=(0,))
        r = mittarit.passiiviset(av, su, A, A + timedelta(days=2), 1000.0)
        self.assertAlmostEqual(r["osta_ja_pida"][0], 1000.0 / K / 200 * 300, 6)   # ostettu paivan 1 avaukseen

    def test_ei_dataa_palauttaa_none(self):
        self.assertIsNone(mittarit.passiiviset({}, {}, A, A + timedelta(days=3)))
        av, su = sarja(3)
        self.assertIsNone(mittarit.passiiviset(av, su, A, A - timedelta(days=1)))

    def test_sama_kuin_vertailusalkku(self):
        con = db.avaa(":memory:")
        rivit = [(paiva._ms(A + timedelta(days=i)), 100 + i, 0, 0, 105 + i, 1.0, 1.0, 1) for i in range(10)]
        db.lisaa_hinnat(con, "BTCUSDT", rivit)
        v = mittarit.vertailusalkku(con, {"BTCUSDT": 1.0}, A, A + timedelta(days=9))[-1][1]
        av = {A + timedelta(days=i): 100.0 + i for i in range(10)}
        su = {A + timedelta(days=i): 105.0 + i for i in range(10)}
        self.assertAlmostEqual(mittarit.passiiviset(av, su, A, A + timedelta(days=9))["osta_ja_pida"][0], v, 6)

    def test_rivi(self):
        av, su = sarja(2)
        p = mittarit.passiiviset(av, su, A, A + timedelta(days=1))
        teksti = mittarit.vertailurivi(0.0, p)
        self.assertTrue(teksti.startswith("vs. BTC osta ja pida: +"))
        self.assertIn(", vs. DCA: +", teksti)
        self.assertIn("ei saatavilla", mittarit.vertailurivi(0.0, None))

    def test_paivarivi_ei_kaada_tyhjalla_kannalla(self):
        con = db.avaa(":memory:")
        self.assertIn("ei saatavilla", paiva.passiivirivi(con, "2026-10-15", "2026-10-20", 0.0))
        self.assertIn("ei saatavilla", paiva.passiivirivi(con, None, "2026-10-20", 0.0))
        self.assertIn("ei saatavilla", paiva.passiivirivi(con, "virhe", "2026-10-20", 0.0))


class KertymaRiviTesti(unittest.TestCase):
    """Kasin lasketut odotusarvot: avaus 100, sulku 200, K = (1+liukuma)(1+kulu)."""

    def _rivi(self, paivia_yht, puuttuu=(), salkku_tuotto=1.0, loppu=5):
        con = db.avaa(":memory:")
        rivit = [(paiva._ms(A + timedelta(days=i)), 100.0, 0, 0, 200.0, 1.0, 1.0, 1)
                 for i in range(paivia_yht) if i not in puuttuu]
        db.lisaa_hinnat(con, "BTCUSDT", rivit)
        return paiva.passiivirivi(con, A.isoformat(), (A + timedelta(days=loppu)).isoformat(), salkku_tuotto)

    def test_kasin_laskettu_rivi_ja_paivat(self):
        # osta ja pida: 2/K - 1 = 99,6006 %, ero salkkuun (100 %) = +0,40 pp
        # DCA, vain 1. era ostettu: (2/K - 1)/3 = 33,2002 %, ero = +66,80 pp
        self.assertEqual(self._rivi(6),
                         "vs. BTC osta ja pida: +0.40 %-yks, vs. DCA: +66.80 %-yks (5 pv, alle portin 1 aikarajan)")

    def test_puuttuva_paiva_ja_puuttuva_loppupaiva(self):
        # paiva 2 puuttuu keskelta ja loppupaiva 5 puuttuu: sama tulos (edellinen sulku 200)
        self.assertEqual(self._rivi(6, puuttuu=(2, 5)),
                         "vs. BTC osta ja pida: +0.40 %-yks, vs. DCA: +66.80 %-yks (5 pv, alle portin 1 aikarajan)")

    def test_90_paivaa_ei_alle_rajan_merkintaa(self):
        teksti = self._rivi(95, loppu=90)
        self.assertTrue(teksti.endswith("(90 pv)"), teksti)
        self.assertNotIn("alle portin 1", teksti)
        self.assertIn("alle portin 1 aikarajan", self._rivi(95, loppu=89))

    def test_ilman_paivia_vanha_muoto(self):
        av, su = sarja(2)
        self.assertNotIn(" pv", mittarit.vertailurivi(0.0, mittarit.passiiviset(av, su, A, A + timedelta(days=1))))


if __name__ == "__main__":
    unittest.main()
