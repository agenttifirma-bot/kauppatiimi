import unittest
from datetime import date

import backtest as bt
import regiimi
from test_k6 import kanta


class RegiimiTesti(unittest.TestCase):
    def setUp(self):
        self.d = bt.Data(kanta(700), 8)
        self.p = date(2026, 4, 1)

    def test_ei_katso_tulevaisuuteen(self):
        """Sama paatos vaikka paivan d ja sen jalkeiset hinnat muutetaan."""
        d_ms = bt._ms(self.p)
        ennen = [regiimi.regiimi_paalla(s, self.d, d_ms) for s in regiimi.SAANNOT]
        for ts in list(self.d.close["BTCUSDT"]):
            if ts >= d_ms:
                self.d.close["BTCUSDT"][ts] *= 7.0
        self.assertEqual(ennen, [regiimi.regiimi_paalla(s, self.d, d_ms) for s in regiimi.SAANNOT])

    def test_data_puuttuu_on_pois(self):
        self.assertFalse(regiimi.trendi_paalla(self.d, bt._ms(date(2020, 1, 1))))
        self.assertFalse(regiimi.vola_matala(self.d, bt._ms(date(2020, 1, 1))))

    def test_molemmat_on_trendin_ja_volan_ja(self):
        d_ms = bt._ms(self.p)
        t, v = regiimi.trendi_paalla(self.d, d_ms), regiimi.vola_matala(self.d, d_ms)
        self.assertEqual(regiimi.regiimi_paalla("molemmat", self.d, d_ms), t and v)

    def test_tuntematon_saanto(self):
        with self.assertRaises(ValueError):
            regiimi.regiimi_paalla("x", self.d, bt._ms(self.p))

    def test_portti_ei_koskaan_ole_sijoitettuna_regiimin_ulkopuolella(self):
        tehdas = regiimi.portti(bt.vain_btc(0.8), "trendi")
        strat = tehdas()
        p = date(2026, 3, 1)
        for _ in range(60):
            ehd = strat(bt._Nakyma(self.d), p, {"BTCUSDT"})
            if not regiimi.trendi_paalla(self.d, bt._ms(p)):
                self.assertEqual(ehd, {})
            p = date.fromordinal(p.toordinal() + 1)

    def test_holdoutia_ei_voi_ajaa(self):
        with self.assertRaises(bt.Holdoutvirhe):
            bt._aja(regiimi.portti(bt.vain_btc(0.8), "trendi"), self.d, date(2026, 4, 10), bt.holdout_alku())


class YlisovitusTesti(unittest.TestCase):
    def test_laskee_eron(self):
        wf = {"foldit": [{"train_sharpe": 2.0, "oos_sharpe": 0.5, "oos_tuotto": 0.1},
                         {"train_sharpe": 1.0, "oos_sharpe": -0.5, "oos_tuotto": -0.1}]}
        y = bt.ylisovitus(wf)
        self.assertAlmostEqual(y["train_sharpe"], 1.5)
        self.assertAlmostEqual(y["oos_sharpe"], 0.0)
        self.assertAlmostEqual(y["ero"], 1.5)
        self.assertEqual(y["oos_positiivisia"], 1)
        self.assertIn("VAHVA YLISOVITUS", bt.ylisovitus_teksti(y))

    def test_tyhja(self):
        y = bt.ylisovitus({"foldit": [{"train_sharpe": -1e9, "oos_sharpe": 0.1, "oos_tuotto": 0.0}]})
        self.assertIsNone(y["ero"])
        self.assertIn("ei laskettavissa", bt.ylisovitus_teksti(y))

    def test_walk_forward_tallentaa_oos_sharpen(self):
        d = bt.Data(kanta(700), 8)
        wf = bt.walk_forward("m", lambda **p: bt.momentum(**p), [{"ikkuna": 30, "k": 3}], d, bt.avaa_rekisteri(":memory:"),
                             alku=date(2025, 6, 1), loppu=date(2026, 4, 1), train_pv=120, testi_pv=30)
        self.assertTrue(all("oos_sharpe" in f for f in wf["foldit"]))


if __name__ == "__main__":
    unittest.main()
