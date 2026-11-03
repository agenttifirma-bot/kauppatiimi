"""llm_veto.py: malli voi vain pienentaa/estaa ostoja; oletus pois; fail closed; kutsukatto; loki. Kielimallin vastaus on mockattu."""
import json
import unittest
from datetime import timedelta

import llm_veto as lv
import paiva as pv
import rajat
import salkku
from test_k3 import ALKU, S, markkina

ENV = {"LLM_BASE_URL": "http://x", "LLM_API_KEY": "k"}
MALLI = rajat.MALLIT["flash"]


def mock(sisalto, kutsut):
    def hae(url, avain, payload):
        kutsut.append(payload)
        return {"choices": [{"message": {"content": sisalto}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    return hae


class SovellaTesti(unittest.TestCase):
    def test_vain_pienentaa_tai_estaa(self):
        nyky, ydin = {"BTCUSDT": 0.05}, {"BTCUSDT": 0.10, "ETHUSDT": 0.08}
        self.assertAlmostEqual(lv.sovella(nyky, ydin, {"BTCUSDT": 0.5})["BTCUSDT"], 0.075)
        t = lv.sovella(nyky, ydin, {"ETHUSDT": 0.0})
        self.assertNotIn("ETHUSDT", t)
        self.assertAlmostEqual(t["BTCUSDT"], 0.10)
        self.assertAlmostEqual(lv.sovella(nyky, ydin, {"BTCUSDT": 5.0})["BTCUSDT"], 0.10)   # clamp
        self.assertNotIn("SOLUSDT", lv.sovella(nyky, ydin, {"SOLUSDT": 1.0}))

    def test_myyntia_ei_voi_estaa(self):
        t = lv.sovella({"BTCUSDT": 0.10, "ETHUSDT": 0.10}, {"BTCUSDT": 0.02}, {"BTCUSDT": 0.0, "ETHUSDT": 0.0})
        self.assertAlmostEqual(t["BTCUSDT"], 0.02)
        self.assertNotIn("ETHUSDT", t)

    def test_esta_kaikki_ostot_mutta_ei_myyntia(self):
        t = lv.esta_kaikki({"BTCUSDT": 0.05, "ETHUSDT": 0.10}, {"BTCUSDT": 0.10, "ETHUSDT": 0.04, "SOLUSDT": 0.06})
        self.assertAlmostEqual(t["BTCUSDT"], 0.05)
        self.assertAlmostEqual(t["ETHUSDT"], 0.04)
        self.assertNotIn("SOLUSDT", t)


class JasennaTesti(unittest.TestCase):
    OL = {"BTCUSDT": (0.0, 0.1)}

    def test_kelvolliset(self):
        v, p = lv.jasenna('```json\n{"veto": {"BTCUSDT": 0.5, "XYZ": 0.0}, "perustelu": "' + "x" * 600 + '"}\n```', self.OL)
        self.assertEqual(v, {"BTCUSDT": 0.5})
        self.assertEqual(len(p), 500)

    def test_kelvottomat(self):
        for t in ("ei jsonia", '{"veto": []}', '{"veto": {"BTCUSDT": 1.5}}', '{"veto": {"BTCUSDT": -0.1}}',
                  '{"veto": {"BTCUSDT": "0"}}', '{"veto": {"BTCUSDT": true}}'):
            with self.assertRaises(lv.Vetovirhe):
                lv.jasenna(t, self.OL)

    def test_tyhja_veto_hyvaksyy(self):
        self.assertEqual(lv.jasenna('{"veto": {}, "perustelu": "ok"}', self.OL), ({}, "ok"))


class SuodataTesti(unittest.TestCase):
    def setUp(self):
        self.mk = markkina({s: [(100, 100)] * 4 for s in S})
        self.sal = salkku.avaa(":memory:", alkupaoma=10000.0)
        self.ydin = {"BTCUSDT": 0.10, "ETHUSDT": 0.08}

    def _aja(self, sisalto, **kw):
        kutsut = []
        t = lv.suodata(self.sal, self.mk, ALKU, self.ydin, S, MALLI, ENV, mock(sisalto, kutsut), paalla=True, **kw)
        return t, kutsut

    def _loki(self):
        return self.sal.execute("SELECT tulos, veto, perustelu FROM veto_loki").fetchall()

    def test_oletus_pois(self):
        self.assertFalse(lv.kaytossa({}))
        self.assertFalse(lv.kaytossa({"KAUPPA_LLM_VETO": "0"}))
        self.assertTrue(lv.kaytossa({"KAUPPA_LLM_VETO": "1"}))
        kutsut = []
        t = lv.suodata(self.sal, self.mk, ALKU, self.ydin, S, MALLI, ENV, mock("{}", kutsut), paalla=False)
        self.assertIs(t, self.ydin)
        self.assertEqual(kutsut, [])

    def test_veto_pienentaa_ja_kirjaa_perustelun(self):
        t, kutsut = self._aja('{"veto": {"BTCUSDT": 0.5, "ETHUSDT": 0.0}, "perustelu": "ETH r7 outo"}')
        self.assertAlmostEqual(t["BTCUSDT"], 0.05)
        self.assertNotIn("ETHUSDT", t)
        self.assertEqual(len(kutsut), 1)
        self.assertEqual(self._loki(), [("ok", json.dumps({"BTCUSDT": 0.5, "ETHUSDT": 0.0}, sort_keys=True), "ETH r7 outo")])

    def test_malli_ei_voi_kasvattaa_eika_lisata(self):
        t, _ = self._aja('{"veto": {"BTCUSDT": 1.0, "SOLUSDT": 1.0}, "perustelu": ""}')
        self.assertEqual(t, self.ydin)

    def test_kaupataan_vedetylla_painolla(self):
        t, _ = self._aja('{"veto": {"BTCUSDT": 0.5}, "perustelu": ""}')
        sim = salkku.suorita_paiva(self.sal, self.mk, ALKU, t, S)
        self.assertEqual(sorted(k[1] for k in sim["kaupat"]), ["BTCUSDT", "ETHUSDT"])

    def test_virheellinen_vastaus_estaa_ostot(self):
        t, _ = self._aja("roskaa")
        self.assertEqual(t, {})
        self.assertEqual(self._loki()[0][0], "virhe")

    def test_llm_virhe_estaa_ostot_mutta_ei_kaada(self):
        def hae(url, avain, payload):
            raise OSError("verkko")
        import llm
        orig = llm.kysy

        def kysy(*a, **k):
            raise llm.LLMVirhe("x")
        llm.kysy = kysy
        try:
            t = lv.suodata(self.sal, self.mk, ALKU, self.ydin, S, MALLI, ENV, hae, paalla=True)
        finally:
            llm.kysy = orig
        self.assertEqual(t, {})

    def test_myynnit_menevat_lapi_virheessa(self):
        salkku.suorita_paiva(self.sal, self.mk, ALKU, {"BTCUSDT": 0.10}, S)
        p = ALKU + timedelta(days=1)
        t = lv.suodata(self.sal, self.mk, p, {"BTCUSDT": 0.02, "ETHUSDT": 0.05}, S, MALLI, ENV, mock("roskaa", []), paalla=True)
        self.assertAlmostEqual(t["BTCUSDT"], 0.02)
        self.assertNotIn("ETHUSDT", t)

    def test_ei_ostoja_ei_kutsua(self):
        kutsut = []
        t = lv.suodata(self.sal, self.mk, ALKU, {}, S, MALLI, ENV, mock("{}", kutsut), paalla=True)
        self.assertEqual((t, kutsut), ({}, []))

    def test_ei_ydinta_tai_tuntematon_malli_ei_kauppoja(self):
        self.assertEqual(lv.suodata(self.sal, self.mk, ALKU, None, S, MALLI, ENV, mock("{}", []), paalla=True), {})
        kutsut = []
        self.assertEqual(lv.suodata(self.sal, self.mk, ALKU, self.ydin, S, "joku-muu", ENV, mock("{}", kutsut), paalla=True), {})
        self.assertEqual(kutsut, [])

    def test_kutsukatto_estaa_ostot_ilman_kutsua(self):
        pv._kutsut_tanaan(self.sal, ALKU)   # luo llm_kutsut-taulun
        for _ in range(rajat.MAX_LLM_KUTSUJA_PAIVA):
            pv._kirjaa_kutsu(self.sal, ALKU, "analyytikko", MALLI, {})
        t, kutsut = self._aja('{"veto": {}}')
        self.assertEqual((t, kutsut), ({}, []))
        self.assertEqual(self._loki()[0][0], "kutsukatto")

    def test_kutsu_kirjataan_kiintioon(self):
        self._aja('{"veto": {}}')
        self.assertEqual(pv._kutsut_tanaan(self.sal, ALKU), 1)


if __name__ == "__main__":
    unittest.main()
