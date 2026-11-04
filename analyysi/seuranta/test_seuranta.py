"""Testit tekoaineistolla. Aja repon juuresta: python3 -m unittest discover -p 'test_*.py'"""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone

from analyysi.seuranta import arvio
from analyysi.seuranta import seuranta as s

ALKU = date(2026, 1, 1)


def rakenna(hakemisto, paivia, hinta=lambda i: 100.0, salkku=lambda i: 10000.0,
            btc_puuttuu=None, paivitetty="2026-03-01T08:00:00+00:00", alku_siirto=None):
    """Tekoaineisto: BTC-hinta funktiona paivan indeksista, salkun arvo samoin.
    alku_siirto: {salkun nimi: paivia}, kuinka monta paivaa myohemmin salkku alkaa."""
    alku_siirto = alku_siirto or {}
    m = sqlite3.connect(hakemisto + "/markkina.db")
    m.execute("create table hinnat (symbol text, ts integer, open real, high real, low real,"
              " close real, volume real, quote_volume real, kaupat integer)")
    for i in range(paivia):
        if btc_puuttuu == i:
            continue
        p = ALKU + timedelta(days=i)
        m.execute("insert into hinnat values ('BTCUSDT',?,?,?,?,?,0,0,0)",
                  (s.ms(p), hinta(i), hinta(i), hinta(i), hinta(i)))
    m.commit()
    m.close()
    for nimi in s.SALKUT:
        c = sqlite3.connect("%s/%s.db" % (hakemisto, nimi))
        c.execute("create table tila (avain text primary key, arvo text not null)")
        c.execute("insert into tila values ('alkupaoma','10000.0')")
        c.execute("create table arvot (paiva text primary key, arvo real, kateinen real, positiot_arvo real)")
        for i in range(alku_siirto.get(nimi, 0), paivia):
            c.execute("insert into arvot values (?,?,0,0)",
                      ((ALKU + timedelta(days=i)).isoformat(), salkku(i)))
        c.commit()
        c.close()
    with open(hakemisto + "/PAIVITETTY", "w") as f:
        f.write(paivitetty + "\n")


class Perus(unittest.TestCase):
    def test_pudotus(self):
        self.assertAlmostEqual(s.pudotus([1, 2, 1, 3, 1.5]), 0.5)
        self.assertEqual(s.pudotus([1, 2, 3]), 0.0)

    def test_ostopaivat_kuukauden_ensimmainen_jakson_paiva(self):
        jakso = list(s.paivat(date(2026, 1, 15), date(2026, 3, 2)))
        self.assertEqual(sorted(s.ostopaivat(jakso)),
                         [date(2026, 1, 15), date(2026, 2, 1), date(2026, 3, 1)])

    def test_bootstrap_toistettava_ja_kaantuu_vakioon(self):
        import random
        x = [0.01 * (i % 5 - 2) for i in range(40)]
        a = s.bootstrap(x, random.Random(1), toistoja=200)
        b = s.bootstrap(x, random.Random(1), toistoja=200)
        self.assertEqual(a, b)
        v = s.bootstrap([0.5] * 10, random.Random(1), toistoja=50)
        self.assertEqual(v, (0.5, 0.5))


class Passiiviset(unittest.TestCase):
    def setUp(self):
        self.avaus = {s.ms(ALKU + timedelta(days=i)): 100.0 for i in range(60)}
        self.sulku = dict(self.avaus)

    def test_tasainen_hinta_kulu_ostossa(self):
        jakso = list(s.paivat(ALKU, ALKU + timedelta(days=9)))
        bh = s.passiivi_bh(jakso, self.avaus, self.sulku)
        self.assertAlmostEqual(bh[-1], 1 / 1.002)

    def test_era_ja_saasto_samat_ostot_sama_tuotto(self):
        # hinta nousee ja laskee: tuotto sama, pudotus voi erota
        for i in range(60):
            t = s.ms(ALKU + timedelta(days=i))
            self.avaus[t] = self.sulku[t] = 100.0 + (20 if 10 <= i < 20 else 0) - (30 if i >= 40 else 0)
        jakso = list(s.paivat(ALKU, ALKU + timedelta(days=59)))
        era = s.passiivi_era(jakso, self.avaus, self.sulku)
        sv, talletettu, tuotot = s.passiivi_saasto(jakso, self.avaus, self.sulku)
        self.assertAlmostEqual(talletettu, 1.0)
        self.assertAlmostEqual(era[-1] - 1, sv[-1] / talletettu - 1)
        # saastossa kateista ei ole, joten pudotus ei ole pienempi kuin erissa
        self.assertGreaterEqual(s.pudotus(sv) + 1e-12, s.pudotus(era))
        self.assertEqual(len(tuotot), len(jakso))

    def test_era_kateinen_pehmentaa(self):
        for i in range(60):
            t = s.ms(ALKU + timedelta(days=i))
            self.avaus[t] = self.sulku[t] = 100.0 if i < 3 else 50.0
        jakso = list(s.paivat(ALKU, ALKU + timedelta(days=59)))
        era = s.passiivi_era(jakso, self.avaus, self.sulku)
        bh = s.passiivi_bh(jakso, self.avaus, self.sulku)
        self.assertLess(s.pudotus(era), s.pudotus(bh))


class Kokonaisuus(unittest.TestCase):
    def test_lyhyt_jakso_ei_valia(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 20)
            t = s.laske(d)
            self.assertEqual(t["paivia"], 20)
            for sal in t["salkut"]:
                for v in sal["vertailut"]:
                    self.assertIsNone(v["vali"])
            teksti = s.muotoile(t, "x")
            self.assertIn("data ei riit\u00e4", teksti)
            self.assertIn("Johtop\u00e4\u00e4t\u00f6ksi\u00e4 ei tehd\u00e4", teksti)
            self.assertNotIn("\u20ac", teksti)
            self.assertNotIn("EUR", teksti)

    def test_30_paivaa_antaa_valin(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 30, hinta=lambda i: 100 + (i % 7), salkku=lambda i: 10000 + 3 * i)
            t = s.laske(d)
            self.assertEqual(t["paivia"], 30)
            for sal in t["salkut"]:
                for v in sal["vertailut"]:
                    lo, hi = v["vali"]
                    self.assertLessEqual(lo, hi)

    def test_tulos_toistettava(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 35, hinta=lambda i: 100 + (i % 5), salkku=lambda i: 10000 - 2 * i)
            self.assertEqual(s.laske(d), s.laske(d))

    def test_salkun_tuotto_ja_loppu_rajaus(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 40, salkku=lambda i: 10000 + 10 * i)
            t = s.laske(d, loppu=ALKU + timedelta(days=9))
            self.assertEqual(t["paivia"], 10)
            self.assertAlmostEqual(t["salkut"][0]["tuotto"], 90 / 10000)
            self.assertEqual(t["salkut"][0]["pudotus"], 0.0)

    def test_eri_aloituspaivat_lahtoarvo_on_jakson_alkua_edeltava_paiva(self):
        # flash alkaa paivasta 0, pro paivasta 10: jakso alkaa paivasta 10.
        # Flashin arvo kasvaa +100/pv, joten jaksoa edeltanyt kehitys (10000 -> 10900)
        # ei saa kuulua jakson tuottoon. Oikea lahtoarvo on paivan 9 arvo 10900.
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 40, salkku=lambda i: 10000 + 100 * i, alku_siirto={"salkku_pro": 10})
            t = s.laske(d)
            self.assertEqual(t["alku"], ALKU + timedelta(days=10))
            flash, pro = t["salkut"]
            self.assertEqual(flash["nimi"], "salkku_flash")
            # jakson viimeinen paiva 39: arvo 13900, lahto 10900
            self.assertAlmostEqual(flash["tuotto"], 13900 / 10900 - 1)
            # pro alkaa jakson ensimmaisena paivana: lahtoarvo on alkupaoma 10000
            self.assertAlmostEqual(pro["tuotto"], 13900 / 10000 - 1)

    def test_eri_aloituspaivat_arvio_samat_lahtoarvot(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 40, salkku=lambda i: 10000 + 100 * i, alku_siirto={"salkku_pro": 10})
            r = arvio.arvioi(d, toistoja=1000)
            # tasainen BTC: passiivisen tuotto on kulun verran miinuksella, sama kaikille
            flash = [x for x in r["rivit"] if x["tapa"] == "salkku_flash"][0]
            self.assertAlmostEqual(flash["ero_kum"] + 0.0, (13900 / 10900 - 1) - (1 / 1.002 - 1))
            self.assertEqual(flash["paivia"], 30)

    def test_aukko_ennen_jaksoa_antaa_virheen(self):
        # flash alkaa paivasta 0 mutta paivan 9 rivi puuttuu: lahtoarvoa ei voi paatella
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 40, alku_siirto={"salkku_pro": 10})
            c = sqlite3.connect(d + "/salkku_flash.db")
            c.execute("delete from arvot where paiva=?", ((ALKU + timedelta(days=9)).isoformat(),))
            c.commit()
            c.close()
            with self.assertRaises(ValueError):
                s.laske(d)

    def test_btc_hinta_puuttuu_antaa_virheen(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 20, btc_puuttuu=5)
            with self.assertRaises(ValueError):
                s.laske(d)

    def test_lukee_vain_eika_muuta_tiedostoja(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 20)
            ennen = {f: (os.stat(d + "/" + f).st_mtime_ns, os.stat(d + "/" + f).st_size)
                     for f in os.listdir(d)}
            os.chmod(d, 0o500)  # hakemistoon ei saa luoda (esim. journal-tiedostoja)
            try:
                s.laske(d)
            finally:
                os.chmod(d, 0o700)
            jalkeen = {f: (os.stat(d + "/" + f).st_mtime_ns, os.stat(d + "/" + f).st_size)
                       for f in os.listdir(d)}
            self.assertEqual(ennen, jalkeen)

    def test_main_tulostaa_ja_virhe_vain_tyyppi(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 20)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(s.main([d]), 0)
            self.assertIn("salkku_flash", out.getvalue())
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(s.main([d]), 1)
            self.assertRegex(out.getvalue().strip(), r"^virhe: \w+$")


class Argumentit(unittest.TestCase):
    def test_virheellinen_argumentti_antaa_virheen_eika_tracebackia(self):
        for modyyli in (s, arvio):
            for argv in (["/tmp", "--loppu"], ["/tmp", "--loppu", "xx"]):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(modyyli.main(argv), 1)
                self.assertRegex(out.getvalue().strip(), r"^virhe: \w+$")


class Tuoreus(unittest.TestCase):
    def test_vanha_merkitaan(self):
        with tempfile.TemporaryDirectory() as d:
            rakenna(d, 5, paivitetty="2026-03-01T08:00:00+00:00")
            nyt = datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc)
            teksti, ika = s.tuoreus(d, nyt)
            self.assertAlmostEqual(ika, 48.0)
            self.assertIn("VANHA", teksti)
            teksti, _ = s.tuoreus(d, datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc))
            self.assertNotIn("VANHA", teksti)

    def test_puuttuva_tiedosto(self):
        with tempfile.TemporaryDirectory() as d:
            teksti, ika = s.tuoreus(d)
            self.assertIsNone(ika)
            self.assertIn("tuntematon", teksti)


if __name__ == "__main__":
    unittest.main()
