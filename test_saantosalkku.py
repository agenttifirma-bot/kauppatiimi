import unittest
from datetime import date, timedelta

import backtest as bt
import rajat
import saantosalkku as ss
from test_k6 import kanta


class PainoTesti(unittest.TestCase):
    def test_tasapaino_ja_katto(self):
        p = ss._painot(["A", "B"], 0.8)
        self.assertEqual(p, {"A": rajat.MAX_POSITIO, "B": rajat.MAX_POSITIO})   # 0.4 -> katto
        p = ss._painot(["A", "B", "C", "D", "E", "F"], 0.6)
        self.assertAlmostEqual(sum(p.values()), 0.6)

    def test_kaanteinen_vol(self):
        p = ss._painot(["A", "B"], 0.2, {"A": 0.01, "B": 0.03})
        self.assertGreater(p["A"], p["B"])
        self.assertLessEqual(max(p.values()), rajat.MAX_POSITIO)
        self.assertEqual(ss._painot([], 0.8), {})


class StrategiaTesti(unittest.TestCase):
    def setUp(self):
        self.con = kanta(400, seed=4)
        self.d = bt.Data(self.con, 8)
        self.a, self.b = date(2026, 1, 1), date(2026, 3, 1)

    def test_trendi_valitsee_vain_ylittajat(self):
        d_ms = bt._ms(date(2026, 3, 1))
        sallitut = self.d.universum(d_ms)
        p = ss.trendi(50)()(self.d, date(2026, 3, 1), sallitut)
        for s in p:
            c = self.d.sulut(s, d_ms, 50)
            self.assertGreater(c[-1], sum(c) / 50)

    def test_ajot_deterministisia_ja_pituus(self):
        for th in (ss.trendi(50), ss.voltti(20), ss.trendi_voltti(50, 20)):
            r1 = bt._aja(th, self.d, self.a, self.b)
            r2 = bt._aja(th, self.d, self.a, self.b)
            self.assertEqual(r1, r2)
            self.assertEqual(len(r1[0]), (self.b - self.a).days + 2)

    def test_ei_katso_tulevaisuuteen(self):
        T = date(2026, 3, 1)
        con2 = kanta(400, seed=4)
        con2.execute("UPDATE hinnat SET close=close*3, open=open*3, high=high*3, low=low*3 WHERE ts>?", (bt._ms(T),))
        d2 = bt.Data(con2, 8)
        r1 = bt._aja(ss.trendi_voltti(50, 20), self.d, self.a, T)
        r2 = bt._aja(ss.trendi_voltti(50, 20), d2, self.a, T)
        self.assertEqual(r1, r2)


class VertailuTesti(unittest.TestCase):
    def setUp(self):
        self.d = bt.Data(kanta(400, seed=4), 8)
        self.a, self.b = date(2026, 1, 5), date(2026, 3, 20)

    def test_btc_ja_dca_kulut(self):
        a = ss.btc_osta_pida(self.d, self.a, self.b)
        self.assertEqual(len(a), (self.b - self.a).days + 2)
        self.assertEqual(a[0], rajat.ALKUPAOMA)
        # ensimmaisen paivan jalkeen arvo ei ylita alkupaomaa enempaa kuin paivan hintaliike sallii; kulu pienentaa osuutta
        q = rajat.ALKUPAOMA * 0.8 / (self.d.open["BTCUSDT"][bt._ms(self.a)] * (1 + rajat.SLIPPAGE) * (1 + rajat.KULU))
        self.assertAlmostEqual(a[1], rajat.ALKUPAOMA * 0.2 + q * self.d.close["BTCUSDT"][bt._ms(self.a)])

    def test_dca_ostopaivat(self):
        self.assertEqual(ss._kuukausialut(self.a, self.b), [date(2026, 1, 5), date(2026, 2, 1), date(2026, 3, 1)])
        a = ss.dca(self.d, self.a, self.b)
        self.assertEqual(len(a), (self.b - self.a).days + 2)
        # rahaa ei synny tyhjasta: nollakulu-rajalla arvo ~ alkupaoma; tasa-hinta -> arvo laskee vain kuluista
        for s in self.d.close:
            for ts in self.d.close[s]:
                self.d.close[s][ts] = self.d.open[s][ts] = 100.0
        tasa = ss.dca(self.d, self.a, self.b)
        self.assertLess(tasa[-1], rajat.ALKUPAOMA)
        self.assertGreater(tasa[-1], rajat.ALKUPAOMA * (1 - 0.8 * 3 * (rajat.KULU + rajat.SLIPPAGE)) - 1)

    def test_vertaile_kieltaytyy_holdoutista(self):
        with self.assertRaises(bt.Holdoutvirhe):
            ss.vertaile(self.d, self.a, bt.holdout_alku())

    def test_vertaile_ja_taulukko(self):
        t = ss.vertaile(self.d, self.a, self.b)
        self.assertIn("btc_osta_pida", t["jatkuva"])
        self.assertIn("dca_kuukausi", t["jatkuva"])
        self.assertIn("trendi100", t["ikkunat90"])
        self.assertIn("| trendi100+voltti30 |", ss.taulukko(t))

    def test_ikkunat(self):
        w = ss.ikkunat_90(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(w), 4)
        self.assertEqual(w[1][0], w[0][1] + timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
