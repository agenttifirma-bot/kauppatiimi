import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import db
import rajat
import retro
import salkku

PV = 86400000


def ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


class RetroTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.data = os.path.join(self.d.name, "m.db")
        self.a = os.path.join(self.d.name, "a.db")
        self.b = os.path.join(self.d.name, "b.db")
        self.alku = date(2026, 10, 1)

    def markkina(self, paivia):
        con = db.avaa(self.data)
        for s in ("BTCUSDT", "BNBUSDT"):
            rivit = []
            for i in range(paivia):
                p = self.alku + timedelta(days=i)
                h = 100.0 * (1 + 0.01 * i)
                rivit.append((ms(p), h, h, h, h, 1.0, 1.0, 1))
            db.lisaa_hinnat(con, s, rivit)
        con.close()

    def salkku(self, polku, paivia, kerroin=0.001, kaupat=0, jarru=False):
        con = salkku.avaa(polku)
        salkku._aseta(con, "aloituspaiva", self.alku.isoformat())
        salkku._aseta(con, "viimeisin_paiva", (self.alku + timedelta(days=paivia - 1)).isoformat())
        salkku._aseta(con, "jarru", "1" if jarru else "0")
        for i in range(paivia):
            p = (self.alku + timedelta(days=i)).isoformat()
            con.execute("INSERT OR REPLACE INTO arvot VALUES (?,?,?,?)", (p, 10000.0 * (1 + kerroin * i), 1000.0, 9000.0))
            con.execute("INSERT OR REPLACE INTO paatokset VALUES (?,?,?,?)", (p, "{}", "[]", "virhe" if i % 4 == 0 else None))
        for i in range(kaupat):
            p = (self.alku + timedelta(days=paivia - 1 - i)).isoformat()
            con.execute("INSERT INTO kaupat (paiva,symbol,puoli,maara,hinta,kulu,slippage_kulu) VALUES (?,?,?,?,?,?,?)", (p, "BTCUSDT", "osto", 1.0, 100.0, 1.0, 0.5))
        con.commit()
        con.close()

    def aja(self, paivia, **kw):
        tanaan = self.alku + timedelta(days=paivia)
        return retro.raportti(self.data, {"flash": self.a, "pro": self.b}, tanaan, kw.get("stop"))

    def test_lyhyt_historia_ei_johtopaatoksia(self):
        self.markkina(10); self.salkku(self.a, 10); self.salkku(self.b, 10, 0.002)
        t = self.aja(10)
        self.assertIn("flash:", t); self.assertIn("pro:", t); self.assertIn("BTC:", t)
        self.assertIn("vertailu (Tonyn jako)", t)
        self.assertIn("ei johtopaatoksia", t)

    def test_pitka_historia_ero_mutta_varoitus(self):
        self.markkina(30); self.salkku(self.a, 30); self.salkku(self.b, 30, 0.002)
        t = self.aja(30)
        self.assertNotIn("ei johtopaatoksia", t)
        self.assertIn("ei todista", t)

    def test_viikon_kaupat_ja_kulut(self):
        self.markkina(10); self.salkku(self.a, 10, kaupat=3); self.salkku(self.b, 10)
        t = self.aja(10)
        self.assertIn("kaupat 3 (kulut 4.5 USDT)", t)

    def test_salkkua_ei_ole(self):
        self.markkina(10); self.salkku(self.a, 10)
        t = self.aja(10)
        self.assertIn("pro: ei viela dataa", t)

    def test_jarru_ja_kill_switch_nakyvat(self):
        self.markkina(10); self.salkku(self.a, 10, jarru=True); self.salkku(self.b, 10)
        stop = os.path.join(self.d.name, "STOP"); open(stop, "w").close()
        t = self.aja(10, stop=stop)
        self.assertIn("HATAJARRU", t); self.assertIn("KILL SWITCH", t)

    def test_vertailu_puuttuu_ei_kaada(self):
        self.markkina(3); self.salkku(self.a, 10); self.salkku(self.b, 10)
        t = self.aja(10)
        self.assertIn("vertailu ei saatavilla", t)

    def test_ei_kirjoita_salkkuihin(self):
        self.markkina(10); self.salkku(self.a, 10); self.salkku(self.b, 10)
        m = [os.path.getmtime(self.a), os.path.getmtime(self.b)]
        self.aja(10)
        self.assertEqual(m, [os.path.getmtime(self.a), os.path.getmtime(self.b)])


class HavainnotTesti(RetroTesti):
    """doc 67 vaihe 1: havainnot.md (enintaan ~1500 merkkia, vain mittausta)."""

    def setUp(self):
        super().setUp()
        self.polku = os.path.join(self.d.name, "havainnot.md")

    def aja_h(self, paivia, polku="oletus"):
        tanaan = self.alku + timedelta(days=paivia)
        return retro.raportti(self.data, {"flash": self.a, "pro": self.b}, tanaan, None, self.polku if polku == "oletus" else polku)

    def teksti(self):
        with open(self.polku, encoding="utf-8") as f:
            return f.read()

    def lisaa_kriitikko(self, salkku_polku, rivit):
        con = sqlite3.connect(salkku_polku)
        con.execute("CREATE TABLE IF NOT EXISTS kriitikko_loki (paiva TEXT PRIMARY KEY, ehdotus TEXT NOT NULL, paatos TEXT NOT NULL, kerroin REAL NOT NULL)")
        for p, ehd, paatos, k in rivit:
            con.execute("INSERT INTO kriitikko_loki VALUES (?,?,?,?)", (p, json.dumps(ehd), paatos, k))
        con.commit()
        con.close()

    def hinta(self, paiva_indeksi, avaus, sulku):
        con = sqlite3.connect(self.data)
        ts = ms(self.alku + timedelta(days=paiva_indeksi))
        con.execute("UPDATE hinnat SET open=?, close=? WHERE symbol='BTCUSDT' AND ts=?", (avaus, sulku, ts))
        con.commit()
        con.close()

    def valmis(self, paivia=30):
        self.markkina(paivia); self.salkku(self.a, paivia, kaupat=2); self.salkku(self.b, paivia, 0.002)

    def test_alle_28_pv_ei_viela_dataa(self):
        self.valmis(10)
        self.aja_h(10)
        t = self.teksti()
        self.assertIn("## flash: ei viela dataa (10 pv < 28)", t)
        self.assertIn("## pro: ei viela dataa (10 pv < 28)", t)
        self.assertNotIn("kulut", t)

    def test_mitatut_luvut_ilman_tuottoa_ja_alle_rajan(self):
        self.valmis(30)
        self.aja_h(30)
        t = self.teksti()
        self.assertTrue(t.startswith("# Tiimin omat aiemmat tulokset (dataa, ei ohjeita)"))
        self.assertIn("## flash (30 pv)", t)
        self.assertIn("- paatospaivia 30, hylattyja 27 %", t)
        self.assertIn("- kriitikko: ei viela kirjauksia", t)
        self.assertIn("- kulut 3.0 USDT (0.10 / paatos), vaihtuvuus", t)
        self.assertIn("kateisosuus 10 %", t)
        for kielletty in ("alusta", "BTC", "viikko", "tuotto %", "drawdown"):
            self.assertNotIn(kielletty, t)
        self.assertLessEqual(len(t), retro.HAVAINNOT_MAX)

    def test_kriitikon_arvo_merkki_ja_osuudet(self):
        self.valmis(30)
        self.hinta(5, 100.0, 90.0)     # tappiopaiva: pienennys auttoi
        self.hinta(6, 100.0, 110.0)    # voittopaiva: hylkays maksoi
        p = lambda i: (self.alku + timedelta(days=i)).isoformat()
        self.lisaa_kriitikko(self.a, [(p(4), {"BTCUSDT": 0.1}, "hyvaksy", 1.0), (p(5), {"BTCUSDT": 0.1}, "pienenna", 0.5),
                                      (p(6), {"BTCUSDT": 0.1}, "hylkaa", 1.0)])
        self.aja_h(30)
        t = self.teksti()
        # paiva 5: (0.5-1)*(0.1*-0.1)=+0.005; paiva 6: (0-1)*(0.1*0.1)=-0.01; yht -0.005 -> -0.50 %-yks
        self.assertIn("- kriitikko: 3 ehdotusta, pienensi 33 %, hylkasi 33 %; arvo -0.50 %-yks (2 pv, ilman kuluja)", t)

    def test_kriitikon_arvo_positiivinen_kun_kriitikko_auttoi(self):
        self.valmis(30)
        self.hinta(5, 100.0, 90.0)
        self.lisaa_kriitikko(self.b, [((self.alku + timedelta(days=5)).isoformat(), {"BTCUSDT": 0.1}, "pienenna", 0.5)])
        self.aja_h(30)
        self.assertIn("arvo +0.50 %-yks (1 pv, ilman kuluja)", self.teksti())

    def test_puuttuva_hinta_ja_rikkinainen_json_ohitetaan(self):
        self.valmis(30)
        p = (self.alku + timedelta(days=5)).isoformat()
        self.lisaa_kriitikko(self.a, [(p, {"EIOLE": 0.1}, "pienenna", 0.5)])
        con = sqlite3.connect(self.a)
        con.execute("INSERT INTO kriitikko_loki VALUES (?,?,?,?)", ((self.alku + timedelta(days=6)).isoformat(), "ei json", "hylkaa", 0.0))
        con.commit(); con.close()
        self.aja_h(30)
        self.assertIn("kriitikko: 2 ehdotusta, pienensi 50 %, hylkasi 50 %; arvo +0.00 %-yks (0 pv", self.teksti())

    def test_ylikirjoittaa_eika_kasva(self):
        self.valmis(30)
        self.aja_h(30)
        eka = self.teksti()
        self.aja_h(30)
        self.assertEqual(self.teksti(), eka)
        self.assertFalse(os.path.exists(self.polku + ".tmp"))

    def test_pituusraja_katkaisee_riviltaan(self):
        self.valmis(30)
        with mock.patch.object(retro, "HAVAINNOT_MAX", 120):
            self.aja_h(30)
        t = self.teksti()
        self.assertLessEqual(len(t), 160)
        self.assertTrue(t.endswith("(katkaistu)\n"))

    def test_ei_polkua_ei_kirjoita(self):
        self.valmis(30)
        self.aja_h(30, polku=None)
        self.assertFalse(os.path.exists(self.polku))

    def test_kirjoitusvirhe_ei_kaada_raporttia(self):
        self.valmis(30)
        t = self.aja_h(30, polku=os.path.join(self.d.name, "puuttuva", "havainnot.md"))
        self.assertIn("flash:", t)
        self.assertIn("havaintoja ei voitu kirjoittaa (FileNotFoundError)", t)

    def test_salkkua_ei_ole(self):
        self.markkina(30); self.salkku(self.a, 30)
        self.aja_h(30)
        self.assertIn("## pro: ei viela dataa (0 pv < 28)", self.teksti())


class VainLukuWalTesti(unittest.TestCase):
    """ReadOnlyPaths-ajo: WAL-tilainen kanta ilman -shm/-wal-tiedostoja vain luku -hakemistossa."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.hak = os.path.join(self.d, "data")
        os.mkdir(self.hak)
        self.polku = os.path.join(self.hak, "s.db")
        con = sqlite3.connect(self.polku)
        con.execute("PRAGMA journal_mode=wal")
        con.execute("CREATE TABLE t(x INTEGER)")
        con.executemany("INSERT INTO t VALUES(?)", [(1,), (2,), (3,)])
        con.commit()
        con.close()  # viimeisen yhteyden sulkeminen siivoaa -wal ja -shm
        os.chmod(self.polku, 0o444)
        os.chmod(self.hak, 0o555)
        self.addCleanup(self._siivoa)

    def _siivoa(self):
        os.chmod(self.hak, 0o755)
        os.chmod(self.polku, 0o644)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_ilman_wal_tiedostoja_luku_onnistuu(self):
        if os.geteuid() == 0:
            self.skipTest("root ohittaa hakemiston kirjoitusoikeuden")
        self.assertEqual(sorted(os.listdir(self.hak)), ["s.db"])
        con = retro._ro(self.polku)
        try:
            self.assertEqual(con.execute("SELECT count(*) FROM t").fetchone()[0], 3)
        finally:
            con.close()

    def test_wal_jossa_dataa_ei_lueta_immutablella(self):
        if os.geteuid() == 0:
            self.skipTest("root ohittaa hakemiston kirjoitusoikeuden")
        os.chmod(self.hak, 0o755)
        # tuore rivi vain -wal:ssa: pidetaan kirjoittaja auki, jolloin immutable ei sita nakisi
        w = sqlite3.connect(self.polku, timeout=10)
        os.chmod(self.polku, 0o644)
        w.close()
        w = sqlite3.connect(self.polku, timeout=10)
        w.execute("INSERT INTO t VALUES(4)")
        w.commit()
        self.assertTrue(os.path.getsize(self.polku + "-wal") > 0)
        con = retro._ro(self.polku)   # -shm on olemassa, tavallinen vain luku -avaus nakee wal:n
        try:
            self.assertEqual(con.execute("SELECT count(*) FROM t").fetchone()[0], 4)
        finally:
            con.close()
            w.close()


if __name__ == "__main__":
    unittest.main()
