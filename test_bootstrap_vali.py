import random
import unittest
from unittest import mock

import bootstrap_vali as bv

A = [0.01, -0.02, 0.03, 0.00, -0.01, 0.02, 0.01, -0.03, 0.02, 0.01] * 6
B = [0.005, 0.01, -0.01, 0.02, 0.00, -0.02, 0.01, 0.00, -0.01, 0.02] * 6


class BootstrapValiTesti(unittest.TestCase):
    def test_sama_siemen_sama_tulos(self):
        self.assertEqual(bv.bootstrap_ero(A, B, 5, 200, 7), bv.bootstrap_ero(A, B, 5, 200, 7))

    def test_eri_siemen_eri_tulos(self):
        self.assertNotEqual(bv.bootstrap_ero(A, B, 5, 200, 7), bv.bootstrap_ero(A, B, 5, 200, 8))

    def test_indeksit_pituus_ja_lohkot(self):
        ix = bv.indeksit(50, 10, random.Random(3))
        self.assertEqual(len(ix), 50)
        self.assertTrue(all(0 <= i < 50 for i in ix))
        for k in range(0, 50, 10):
            for j in range(1, 10):
                self.assertEqual(ix[k + j], (ix[k] + j) % 50)

    def test_parillinen_otanta_kayttaa_samoja_indekseja(self):
        # a on indeksisarja 0..n-1, b = a + 1: jos indeksit ovat samat, erotuksen tuotto on kiintea
        n = 40
        kutsut = []
        alku = bv.indeksit

        def seuraa(n_, lohko, rng):
            ix = alku(n_, lohko, rng)
            kutsut.append(ix)
            return ix
        a = [0.001 * i for i in range(n)]
        b = [x + 0.01 for x in a]
        with mock.patch.object(bv, "indeksit", seuraa):
            bv.bootstrap_ero(a, b, 7, 50, 1)
        self.assertEqual(len(kutsut), 50)   # yksi indeksilista per toisto, ei kahta
        # yhteinen indeksilista: log-erotus on joka toistossa sama vakio (b nousee tasan 0,01 vain jos
        # indeksit ovat samat), joten vali on kapea
        r = bv.bootstrap_ero([0.0] * n, [0.01] * n, 7, 50, 1)
        self.assertAlmostEqual(r["tuotto"]["vali"][0], r["tuotto"]["vali"][1], 12)

    def test_identtiset_sarjat_ero_nolla(self):
        r = bv.bootstrap_ero(A, list(A), 5, 300, 2)
        for k in ("tuotto", "loki", "mdd"):
            self.assertEqual(r[k]["piste"], 0.0)
            self.assertEqual(r[k]["vali"], (0.0, 0.0))
            self.assertEqual(r[k]["mediaani"], 0.0)

    def test_vakioero_antaa_odotetun_valin(self):
        n = 60
        a = [0.002] * n
        b = [0.001] * n
        r = bv.bootstrap_ero(a, b, 10, 100, 1)
        odotettu = 1.002 ** n - 1.001 ** n
        self.assertAlmostEqual(r["tuotto"]["vali"][0], odotettu, 9)
        self.assertAlmostEqual(r["tuotto"]["vali"][1], odotettu, 9)
        loki = (bv.loki_keskiarvo(a) - bv.loki_keskiarvo(b)) * 365
        self.assertAlmostEqual(r["loki"]["vali"][0], loki, 9)
        self.assertEqual(r["tuotto"]["p_positiivinen"], 1.0)

    def test_enimmaistappio(self):
        self.assertAlmostEqual(bv.enimmaistappio([0.1, -0.5, 0.2]), 0.5)
        self.assertEqual(bv.enimmaistappio([0.1, 0.1]), 0.0)

    def test_persentiili_ja_virheet(self):
        self.assertAlmostEqual(bv.persentiili([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(bv.persentiili([0, 10], 0.05), 0.5)
        with self.assertRaises(ValueError):
            bv.bootstrap_ero([0.1], [0.1, 0.2])
        with self.assertRaises(ValueError):
            bv.indeksit(10, 0, random.Random(1))

    def test_tuotot_arvosarjasta(self):
        t = bv.tuotot([100, 110, 99])
        self.assertAlmostEqual(t[0], 0.10, 12)
        self.assertAlmostEqual(t[1], -0.10, 12)


if __name__ == "__main__":
    unittest.main()
