"""Walk-forward-paivatuotot: valinnainen tallennus kulujen jalkeen (paperiajon mittaus, ei strategiamuutos)."""
import unittest
from datetime import date

import backtest as bt
from test_k6 import kanta

TOLERANSSI = 1e-9   # ketjutus vs kokonaistuotto: vain liukulukuvirhe (tuhansia kertolaskuja), ei mallivirhetta
AJO = dict(alku=date(2025, 1, 1), loppu=date(2026, 4, 10), train_pv=200, testi_pv=60)
RUUDUKKO = [{"ikkuna": 30, "k": 3, "reb": 7}, {"ikkuna": 60, "k": 5, "reb": 14}]


def aja_wf(paivatuotot):
    d = bt.Data(kanta(600), 8)
    rek = bt.avaa_rekisteri(":memory:")
    wf = bt.walk_forward("mom", lambda **p: bt.momentum(**p), RUUDUKKO, d, rek, paivatuotot=paivatuotot, **AJO)
    return wf, rek


def taulut(rek):
    return {r[0] for r in rek.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class PaivatuototTesti(unittest.TestCase):
    def test_ketjutus_tasmaa_kokeilut_riveihin_ja_kokonaistuottoon(self):
        wf, rek = aja_wf(True)
        rivit = rek.execute("SELECT alku, tuotto FROM kokeilut WHERE nimi='mom' AND jakso='wf-oos' ORDER BY alku").fetchall()
        self.assertGreaterEqual(len(rivit), 2)
        kaikki = 1.0
        for alku, tuotto in rivit:
            tulo = 1.0
            n = 0
            for (r,) in rek.execute("SELECT tuotto FROM paivatuotot WHERE nimi='mom' AND jakso='wf-oos' AND alku=? ORDER BY paiva", (alku,)):
                tulo *= 1 + r
                n += 1
            self.assertGreater(n, 50)
            self.assertAlmostEqual(tulo - 1, tuotto, delta=TOLERANSSI)   # jakso kerrallaan
            kaikki *= tulo
        self.assertAlmostEqual(kaikki - 1, wf["mittarit"]["tuotto"], delta=TOLERANSSI)  # koko ketju

    def test_tallennus_pois_ei_luo_taulua_ja_kokeilut_ennallaan(self):
        wf_pois, rek_pois = aja_wf(False)
        self.assertNotIn("paivatuotot", taulut(rek_pois))
        wf_paalla, rek_paalla = aja_wf(True)
        self.assertIn("paivatuotot", taulut(rek_paalla))
        # tallennus ei muuta lukuja eika kokeilut-rivien sisaltoa (aika-sarake pois, se on kellonaika)
        self.assertEqual(wf_pois["arvot"], wf_paalla["arvot"])
        kysely = "SELECT nimi,parametrit,jakso,alku,loppu,tuotto,sharpe,max_dd,kauppoja,versio FROM kokeilut ORDER BY id"
        self.assertEqual(rek_pois.execute(kysely).fetchall(), rek_paalla.execute(kysely).fetchall())

    def test_vain_testijaksot_tallennetaan(self):
        _, rek = aja_wf(True)
        self.assertEqual(rek.execute("SELECT COUNT(*) FROM paivatuotot WHERE jakso!='wf-oos'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
