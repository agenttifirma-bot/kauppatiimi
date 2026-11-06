"""Testit arvio.py:lle. Aja repon juuresta: python3 -m unittest discover -p 'test_*.py'"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

from analyysi.seuranta import arvio
from analyysi.seuranta.test_seuranta import rakenna

JUURI = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class T(unittest.TestCase):
    def test_vakioero_valiloppuu_ero_ymparille(self):
        # kiintea aineisto: ero on joka paiva tasan 0,01 -> vali kutistuu pisteeseen
        lo, hi = arvio.bootstrap_vali([0.01] * 40)
        self.assertAlmostEqual(lo, 0.01, places=12)
        self.assertAlmostEqual(hi, 0.01, places=12)

    def test_tunnettu_ero_erottuu(self):
        d = [0.01 + ((i * 7) % 5 - 2) * 0.001 + (0.0005 if i % 3 == 0 else 0.0) for i in range(121)]
        lo, hi = arvio.bootstrap_vali(d)
        self.assertGreater(lo, 0.0)
        self.assertLess(lo, hi); self.assertGreater(lo, 0.009); self.assertLess(hi, 0.011)
        self.assertEqual(arvio.paatelma((lo, hi), 121), "erottuu")

    def test_nollakeskiarvo_ei_erotu(self):
        d = [0.02 if i % 2 else -0.02 for i in range(120)]
        vali = arvio.bootstrap_vali(d)
        self.assertLessEqual(vali[0], 0.0); self.assertGreaterEqual(vali[1], 0.0)
        self.assertEqual(arvio.paatelma(vali, 120), "ei erotu")

    def test_liian_vahan_dataa(self):
        self.assertEqual(arvio.paatelma((0.01, 0.02), 30), "data ei riit\u00e4")
        self.assertEqual(arvio.paatelma(None, 5), "data ei riit\u00e4")

    def test_siemen_toistettava_ja_toistoraja(self):
        d = [0.01, -0.02, 0.03, 0.0, -0.01, 0.02] * 10
        self.assertEqual(arvio.bootstrap_vali(d), arvio.bootstrap_vali(d))
        with self.assertRaises(ValueError):
            arvio.bootstrap_vali(d, toistoja=999)
        with self.assertRaises(ValueError):
            arvio.bootstrap_vali([])

    def test_arvioi_loppu_rajaa_jakson(self):
        with tempfile.TemporaryDirectory() as h:
            rakenna(h, 40, hinta=lambda i: 100.0 + i, salkku=lambda i: 10000.0 + 5 * i)
            koko = arvio.arvioi(h)
            rajattu = arvio.arvioi(h, loppu=date(2026, 1, 20))
        self.assertEqual(koko["paivia"], 40)
        self.assertEqual(rajattu["paivia"], 20)
        self.assertEqual(len(rajattu["rivit"]), 6)
        self.assertTrue(all(r["paatelma"] == "data ei riit\u00e4" for r in rajattu["rivit"]))

    def test_main_tulostaa_taulukon_ja_virheesta_vain_tyypin(self):
        with tempfile.TemporaryDirectory() as h:
            rakenna(h, 40)
            ulos = io.StringIO()
            with redirect_stdout(ulos):
                self.assertEqual(arvio.main([h, "--loppu", "2026-01-30"]), 0)
            self.assertIn("| tapa | vertailu |", ulos.getvalue())
            self.assertIn("p\u00e4ivi\u00e4 30", ulos.getvalue())
        ulos = io.StringIO()
        with redirect_stdout(ulos):
            self.assertEqual(arvio.main(["/ei/ole/olemassa"]), 1)
        self.assertRegex(ulos.getvalue().strip(), r"^virhe: \w+$")

    def test_moduuli_loytyy_ajettuna_repon_juuresta(self):
        with tempfile.TemporaryDirectory() as h:
            rakenna(h, 40)
            p = subprocess.run([sys.executable, "-m", "analyysi.seuranta.arvio", h],
                               cwd=JUURI, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-200:])
        self.assertIn("| tapa | vertailu |", p.stdout)


if __name__ == "__main__":
    unittest.main()
