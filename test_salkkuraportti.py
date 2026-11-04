import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

import db
import mittarit
import rajat
import salkku
import salkkuraportti as sr

A = date(2026, 11, 1)


def ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


def tee_markkina(polku, paivia=10, btc=lambda i: 100.0, eth=lambda i: 10.0):
    m = db.avaa(polku)
    for sym, f in (("BTCUSDT", btc), ("ETHUSDT", eth)):
        db.lisaa_hinnat(m, sym, [(ms(A + timedelta(days=i)), f(i), f(i), f(i), f(i), 1, 1, 1) for i in range(paivia)])
    m.close()


def tee_salkku(polku, arvot, kaupat=(), paatokset=(), kriitikko=None, alku=1000.0):
    """Suora synteettinen kanta salkku.py:n skeemalla. arvot: [(paiva, arvo)]."""
    con = salkku.avaa(polku, alkupaoma=alku)
    salkku._aseta(con, "aloituspaiva", arvot[0][0])
    salkku._aseta(con, "viimeisin_paiva", arvot[-1][0])
    with con:
        con.executemany("INSERT INTO arvot VALUES (?,?,?,0)", [(p, v, v) for p, v in arvot])
        con.executemany("INSERT INTO kaupat (paiva,symbol,puoli,maara,hinta,kulu,slippage_kulu) VALUES (?,?,?,1,1,?,?)", kaupat)
        con.executemany("INSERT INTO paatokset VALUES (?,?,?,?)", paatokset)
        if kriitikko:
            con.execute("CREATE TABLE kriitikko_loki (paiva TEXT PRIMARY KEY, ehdotus TEXT NOT NULL, paatos TEXT NOT NULL, kerroin REAL NOT NULL)")
            con.executemany("INSERT INTO kriitikko_loki VALUES (?,'{}',?,1.0)", kriitikko)
    con.close()


def p(i):
    return (A + timedelta(days=i)).isoformat()


class Pohja(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.mk = os.path.join(self.td.name, "markkina.db")
        self.sk = os.path.join(self.td.name, "salkku_agentti_1000.db")
        tee_markkina(self.mk)

    def avaa(self):
        s, m = sr.avaa_ro(self.sk), sr.avaa_ro(self.mk)
        self.addCleanup(s.close)
        self.addCleanup(m.close)
        return s, m


class PuhtaatTesti(unittest.TestCase):
    def test_suurin_pudotus(self):
        self.assertAlmostEqual(sr.suurin_pudotus([1000, 1100, 990, 1050, 1200, 1080]), 0.10)
        self.assertEqual(sr.suurin_pudotus([1000, 1010, 1020]), 0.0)
        self.assertEqual(sr.suurin_pudotus([]), 0.0)

    def test_fi_desimaalipilkku(self):
        self.assertEqual(sr.fi(1234.5), "1234,50")
        self.assertEqual(sr.fi_etumerkki(-0.123), "-0,12")
        self.assertEqual(sr.fi_etumerkki(1.0, 1), "+1,0")

    def test_lause_kaupat_ja_syy(self):
        s = sr.lause([("BTCUSDT", "BUY"), ("ETHUSDT", "SELL"), ("BTCUSDT", "BUY")], ["kauppoja rajattu 12 -> 10"], None, "hyvaksy")
        self.assertTrue(s.startswith("Agentti osti BTC ja myi ETH ("))
        self.assertIn("kriitikko: hyvaksy", s)
        self.assertIn("kauppoja rajattu", s)

    def test_lause_ei_kauppoja_hylatty(self):
        s = sr.lause([], ["EI KAUPPOJA: ei ehdotusta"], "ehdotus ei ole sanakirja", "hylkaa")
        self.assertTrue(s.startswith("Agentti ei tehnyt kauppoja (EI KAUPPOJA"))
        self.assertIn("kriitikko: hylkaa", s)

    def test_lause_pituusraja(self):
        s = sr.lause([], ["x" * 500], "h", None)
        self.assertLessEqual(len(s), sr.MAX_LAUSE)

    def test_lahdekoodi_on_ascii(self):
        for nimi in ("salkkuraportti.py", "test_salkkuraportti.py"):
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), nimi), "rb") as f:
                f.read().decode("ascii")


class PaivaraporttiTesti(Pohja):
    def test_luvut_ja_kuusi_rivia(self):
        tee_salkku(self.sk, [(p(0), 990.0), (p(1), 1100.0), (p(2), 1045.0)],
                   kaupat=[(p(2), "BTCUSDT", "BUY", 0.5, 0.25), (p(2), "ETHUSDT", "SELL", 0.5, 0.25), (p(1), "ETHUSDT", "BUY", 1.0, 1.0)],
                   paatokset=[(p(2), "{}", json.dumps(["kauppoja rajattu 12 -> 10"]), None)],
                   kriitikko=[(p(2), "hyvaksy")])
        s, m = self.avaa()
        L = sr.luvut(s, m)
        self.assertEqual(L["paiva"], p(2))
        self.assertEqual(L["paivia"], 3)
        self.assertEqual((L["kauppoja"], L["kauppoja_yht"]), (2, 3))
        self.assertAlmostEqual(L["kulut"], 1.5)
        self.assertAlmostEqual(L["kulut_yht"], 3.5)
        self.assertAlmostEqual(L["pudotus"], 0.05)            # 1100 -> 1045
        self.assertTrue(L["rajattu"])
        teksti = sr.paivaraportti("agentti_1000", L, raja=10)
        rivit = teksti.split("\n")
        self.assertLessEqual(len(rivit), 6)
        self.assertIn("agentti_1000 %s" % p(2), rivit[0])
        self.assertIn("kauppam\u00e4\u00e4r\u00e4raja 10/pv", rivit[0])
        self.assertIn("Arvo 1045,00 \u20ac", rivit[1])
        self.assertIn("p\u00e4iv\u00e4 -55,00 \u20ac (-5,00 %)", rivit[1])
        self.assertIn("alusta +45,00 \u20ac (+4,50 %)", rivit[1])
        self.assertIn("Kauppoja 2 (kulut 1,50 \u20ac), raja tuli vastaan", rivit[2])
        self.assertIn("5,00 %", rivit[3])
        self.assertIn("kuukausiosto 1000 \u20ac", rivit[4])
        self.assertTrue(rivit[5].startswith("Agentti osti BTC ja myi ETH"))

    def test_vertailu_on_mittarit_dca_samalla_alkupaomalla(self):
        tee_markkina(self.mk, paivia=10, btc=lambda i: 100.0 + 10 * i)   # INSERT OR IGNORE: alkuperaiset hinnat jaavat
        tee_salkku(self.sk, [(p(0), 1000.0), (p(1), 1000.0)])
        s, m = self.avaa()
        L = sr.luvut(s, m)
        av = {A + timedelta(days=i): 100.0 for i in range(10)}
        odotettu = mittarit.passiiviset(av, av, A, A + timedelta(days=1), 1000.0)["dca"]
        self.assertAlmostEqual(L["dca"][0], odotettu[0], 9)
        self.assertLess(L["dca"][1], 0)                       # tasainen hinta: vain kulut

    def test_vertailu_puuttuu(self):
        tee_salkku(self.sk, [("2026-01-01", 1000.0)])
        s, m = self.avaa()
        teksti = sr.paivaraportti("x", sr.luvut(s, m))
        self.assertIn("kuukausiosto 1000 \u20ac: ei saatavilla", teksti)

    def test_tuntematon_paiva_on_virhe(self):
        tee_salkku(self.sk, [(p(0), 1000.0)])
        s, m = self.avaa()
        with self.assertRaises(sr.Raporttivirhe):
            sr.luvut(s, m, p(5))

    def test_oikea_salkku_moottori(self):
        """salkku.suorita_paiva tuottaa kannan, jonka raportti lukee (alkupaoma 1000)."""
        tee_markkina(self.mk)
        con = salkku.avaa(self.sk, alkupaoma=1000.0)
        salkku._aseta(con, "aloituspaiva", p(1))
        mk = sqlite3.connect(self.mk)
        sal = {"BTCUSDT", "ETHUSDT"}
        salkku.suorita_paiva(con, mk, A + timedelta(days=1), {"BTCUSDT": 0.10, "ETHUSDT": 0.05}, sal)
        salkku.suorita_paiva(con, mk, A + timedelta(days=2), {"BTCUSDT": 0.10}, sal)
        con.close(); mk.close()
        s, m = self.avaa()
        L = sr.luvut(s, m)
        self.assertEqual(L["alku"], 1000.0)
        self.assertEqual((L["kauppoja"], L["kauppoja_yht"]), (1, 3))
        self.assertLess(L["arvo"], 1000.0)                    # tasainen hinta: kulut pienentavat
        self.assertIn("myi ETH", L["lause"])


class ViikkoTesti(Pohja):
    def test_voittaja_pahin_paiva_ja_rajaosumat(self):
        arvot = [(p(i), v) for i, v in enumerate([1000, 1010, 980, 1000, 1005, 1020, 1030, 1040, 1050])]
        raja = json.dumps(["kauppoja rajattu 11 -> 10"])
        tee_salkku(self.sk, arvot, paatokset=[(p(1), "{}", raja, None), (p(3), "{}", raja, None), (p(8), "{}", raja, None)])
        s, m = self.avaa()
        t = sr.viikkoyhteenveto(s, m, "agentti_1000", p(8))
        rivit = t.split("\n")
        self.assertEqual(rivit[0], "agentti_1000 viikko %s..%s" % (p(2), p(8)))
        self.assertIn("edell\u00e4: salkku", rivit[1])
        self.assertIn("Pahin p\u00e4iv\u00e4: %s -2,97 %% (-30,00 \u20ac)" % p(2), rivit[2])
        self.assertIn("tuli vastaan: 2 kertaa viikolla, 3 alusta", rivit[3])

    def test_kuukausiosto_voittaa(self):
        tee_markkina(self.mk)
        tee_salkku(self.sk, [(p(0), 900.0), (p(1), 900.0)])
        s, m = self.avaa()
        self.assertIn("edell\u00e4: kuukausiosto", sr.viikkoyhteenveto(s, m, "x"))


class MainTesti(Pohja):
    def _aja(self, *arg, laheta=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sr.main(["--salkku-db", self.sk, "--markkina", self.mk] + list(arg), laheta=laheta)
        return rc, out.getvalue()

    def _tiiviste(self):
        with open(self.sk, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def test_ei_kirjoita_kantaan_ja_lahettaa(self):
        tee_salkku(self.sk, [(p(0), 1000.0), (p(1), 1010.0)])
        ennen = self._tiiviste()
        lahetetyt = []
        rc, out = self._aja("--viikko", laheta=lambda t: lahetetyt.append(t) or True)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("agentti_1000 %s" % p(1)))
        self.assertEqual(lahetetyt, [out.rstrip("\n")])
        self.assertIn("viikko", out)
        self.assertEqual(self._tiiviste(), ennen)

    def test_lahetys_epaonnistuu(self):
        tee_salkku(self.sk, [(p(0), 1000.0)])
        rc, out = self._aja(laheta=lambda t: False)
        self.assertEqual(rc, 1)
        self.assertIn("Telegram: lahetys epaonnistui", out)

    def test_puuttuva_kanta_vain_tyyppi(self):
        rc, out = self._aja("--ei-tg", "--nimi", "agentti_1000")
        self.assertEqual(rc, 2)
        self.assertEqual(out.strip(), "Salkkuraportti (agentti_1000): VIRHE Raporttivirhe")

    def test_immutable_lukee(self):
        tee_salkku(self.sk, [(p(0), 1000.0)])
        rc, out = self._aja("--ei-tg", "--immutable")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
