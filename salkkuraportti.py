"""Salkun paivaraportti (enintaan 6 rivia) ja viikkoyhteenveto. VAIN LUKU: avaa salkku- ja markkinakannan read-only,
ei kirjoita mihinkaan, ei kutsu mallia. Tehty Tonyn asetelmaa agentti_1000 varten (4.11.2026), mutta toimii mille
tahansa salkku.py:n kannalle (flash, pro). Luvut ja tapahtumat, ei suosituksia.

Kaytto (repon juuresta):
  python3 salkkuraportti.py --salkku-db /srv/kauppa/data/salkku_agentti_1000.db --nimi agentti_1000 [--viikko] [--ei-tg]
Vertailu = sama alkupaoma passiivisena kuukausiostona (mittarit.passiiviset: 3 tasaeraa 30 pv valein, samat kulut).
Kauppamaararaja luetaan rajat.MAX_KAUPPOJA_PAIVA:sta (ei muuteta taalla)."""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

import mittarit
import rajat

RAJA_MERKKI = "kauppoja rajattu"   # salkku.py:n huomautus, kun kauppamaararaja leikkaa
MAX_LAUSE = 200


class Raporttivirhe(Exception):
    pass


def avaa_ro(polku, immutable=False):
    """Read-only-yhteys. immutable=True vain kopioille, joihin kukaan ei kirjoita (esim. /var/lib/claude-jono/kauppa)."""
    if not os.path.exists(polku):
        raise Raporttivirhe("kantaa ei ole: %s" % os.path.basename(polku))
    return sqlite3.connect("file:%s?%s" % (polku, "immutable=1" if immutable else "mode=ro"), uri=True, timeout=30)


def fi(x, des=2):
    """Suomalainen desimaalipilkku."""
    return ("%.*f" % (des, x)).replace(".", ",")


def fi_etumerkki(x, des=2):
    return ("%+.*f" % (des, x)).replace(".", ",")


def _tila(sal, avain):
    r = sal.execute("SELECT arvo FROM tila WHERE avain=?", (avain,)).fetchone()
    return r[0] if r else None


def _ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


def suurin_pudotus(arvot):
    """arvot: arvosarja (alkupaoma ensin). Suurin lasku edellisesta huipusta, osuutena 0..1."""
    huippu, dd = None, 0.0
    for v in arvot:
        huippu = v if huippu is None or v > huippu else huippu
        if huippu > 0:
            dd = max(dd, 1.0 - v / huippu)
    return dd


def kuukausiosto(markkina, alku, paiva, alkupaoma):
    """Passiivinen kuukausiosto (BTC) samalla alkupaomalla. Palauttaa (arvo, tuotto) tai None."""
    luku = {}
    for sarake in ("open", "close"):
        luku[sarake] = {datetime.fromtimestamp(ts / 1000, timezone.utc).date(): v for ts, v in markkina.execute(
            "SELECT ts, %s FROM hinnat WHERE symbol='BTCUSDT' AND ts>=? AND ts<=?" % sarake, (_ms(alku), _ms(paiva))).fetchall()}
    p = mittarit.passiiviset(luku["open"], luku["close"], alku, paiva, alkupaoma)
    return None if p is None else p["dca"]


def _arvot(sal, asti):
    return sal.execute("SELECT paiva, arvo FROM arvot WHERE paiva<=? ORDER BY paiva", (asti,)).fetchall()


def _paatos(sal, paiva):
    r = sal.execute("SELECT rajaukset, hylatty FROM paatokset WHERE paiva=?", (paiva,)).fetchone()
    if r is None:
        return [], None
    try:
        huom = json.loads(r[0]) if r[0] else []
    except ValueError:
        huom = []
    return (huom if isinstance(huom, list) else []), r[1]


def _kriitikko(sal, paiva):
    try:
        r = sal.execute("SELECT paatos FROM kriitikko_loki WHERE paiva=?", (paiva,)).fetchone()
    except sqlite3.Error:
        return None   # vanha kanta ilman taulua
    return r[0] if r else None


def lause(kaupat, huom, hylatty, kriitikko):
    """Yksi lause: mita agentti teki ja miksi (tapahtumat kannasta, ei tulkintaa)."""
    ostot = sorted({s.replace("USDT", "") for s, puoli in kaupat if puoli == "BUY"})
    myynnit = sorted({s.replace("USDT", "") for s, puoli in kaupat if puoli == "SELL"})
    if kaupat:
        osat = []
        if ostot:
            osat.append("osti " + ", ".join(ostot))
        if myynnit:
            osat.append("myi " + ", ".join(myynnit))
        teksti = "Agentti " + " ja ".join(osat)
        syy = "kriitikko: %s" % kriitikko if kriitikko else "ehdotus toteutettiin"
        if huom:
            syy += "; huom: %s" % huom[0]
    else:
        teksti = "Agentti ei tehnyt kauppoja"
        if hylatty and huom:
            syy = huom[0]
        elif hylatty:
            syy = "ehdotus hyl\u00e4ttiin (%s)" % hylatty
        elif huom:
            syy = huom[0]
        else:
            syy = "ehdotus ei muuttanut painoja yli kauppakynnyksen"
        if kriitikko:
            syy += "; kriitikko: %s" % kriitikko
    s = "%s (%s)." % (teksti, syy)
    return s if len(s) <= MAX_LAUSE else s[:MAX_LAUSE - 3] + "..."


def luvut(sal, markkina, paiva=None):
    """Raportin luvut paivalle paiva (ISO); oletus viimeisin ajettu paiva."""
    alku = _tila(sal, "alkupaoma")
    aloitus = _tila(sal, "aloituspaiva")
    if alku is None:
        raise Raporttivirhe("salkussa ei ole alkupaomaa")
    alku = float(alku)
    paiva = paiva or _tila(sal, "viimeisin_paiva")
    rivit = _arvot(sal, paiva) if paiva else []
    if not rivit or rivit[-1][0] != paiva:
        raise Raporttivirhe("paivalle ei ole arvoa")
    sarja = [alku] + [float(v) for _, v in rivit]
    kaupat = sal.execute("SELECT symbol, puoli, kulu + slippage_kulu FROM kaupat WHERE paiva=?", (paiva,)).fetchall()
    kaikki = sal.execute("SELECT COUNT(*), COALESCE(SUM(kulu + slippage_kulu), 0) FROM kaupat WHERE paiva<=?", (paiva,)).fetchone()
    huom, hylatty = _paatos(sal, paiva)
    a0 = date.fromisoformat(aloitus or rivit[0][0])
    try:
        dca = kuukausiosto(markkina, a0, date.fromisoformat(paiva), alku)
    except (sqlite3.Error, ValueError, TypeError):
        dca = None
    return {
        "paiva": paiva, "aloitus": a0.isoformat(), "paivia": len(rivit), "alku": alku,
        "arvo": sarja[-1], "edellinen": sarja[-2],
        "kauppoja": len(kaupat), "kulut": sum(k[2] for k in kaupat),
        "kauppoja_yht": kaikki[0], "kulut_yht": kaikki[1],
        "pudotus": suurin_pudotus(sarja), "dca": dca,
        "lause": lause([(k[0], k[1]) for k in kaupat], huom, hylatty, _kriitikko(sal, paiva)),
        "rajattu": any(RAJA_MERKKI in str(h) for h in huom),
    }


def paivaraportti(nimi, L, raja=None):
    """Enintaan 6 rivia. L = luvut()."""
    raja = rajat.MAX_KAUPPOJA_PAIVA if raja is None else raja
    alku, arvo, ed = L["alku"], L["arvo"], L["edellinen"]
    rivit = [
        "%s %s (paperi, p\u00e4iv\u00e4 %d, kauppam\u00e4\u00e4r\u00e4raja %d/pv)" % (nimi, L["paiva"], L["paivia"], raja),
        "Arvo %s \u20ac | p\u00e4iv\u00e4 %s \u20ac (%s %%) | alusta %s \u20ac (%s %%)" % (
            fi(arvo), fi_etumerkki(arvo - ed), fi_etumerkki(100 * (arvo / ed - 1)),
            fi_etumerkki(arvo - alku), fi_etumerkki(100 * (arvo / alku - 1))),
        "Kauppoja %d (kulut %s \u20ac)%s | alusta %d kpl, kulut %s \u20ac" % (
            L["kauppoja"], fi(L["kulut"]), ", raja tuli vastaan" if L["rajattu"] else "", L["kauppoja_yht"], fi(L["kulut_yht"])),
        "Suurin pudotus huipusta t\u00e4h\u00e4n menness\u00e4: %s %%" % fi(100 * L["pudotus"]),
    ]
    if L["dca"] is None:
        rivit.append("Vertailu, kuukausiosto %s \u20ac: ei saatavilla" % fi(alku, 0))
    else:
        d_arvo, d_tuotto = L["dca"]
        rivit.append("Vertailu, kuukausiosto %s \u20ac samalta ajalta: %s \u20ac (%s %%), ero %s %%-yks." % (
            fi(alku, 0), fi(d_arvo), fi_etumerkki(100 * d_tuotto), fi_etumerkki(100 * (arvo / alku - 1 - d_tuotto))))
    rivit.append(L["lause"])
    return "\n".join(rivit)


def viikkoyhteenveto(sal, markkina, nimi, loppu=None, paivia=7):
    """Viikon yhteenveto: kumpi voittaa (alusta), pahin paiva viikolla, kauppamaararajan osumat. Enintaan 4 rivia."""
    loppu = loppu or _tila(sal, "viimeisin_paiva")
    L = luvut(sal, markkina, loppu)
    alku_vk = (date.fromisoformat(loppu) - timedelta(days=paivia - 1)).isoformat()
    sarja = [(None, L["alku"])] + [(p, float(v)) for p, v in _arvot(sal, loppu)]
    pahin = None
    for (_, v0), (p, v1) in zip(sarja, sarja[1:]):
        if p >= alku_vk and (pahin is None or v1 / v0 - 1 < pahin[1]):
            pahin = (p, v1 / v0 - 1, v1 - v0)
    osumat_vk = osumat = 0
    for p, r in sal.execute("SELECT paiva, rajaukset FROM paatokset WHERE paiva<=?", (loppu,)):
        if r and RAJA_MERKKI in r:
            osumat += 1
            osumat_vk += p >= alku_vk
    tuotto = L["arvo"] / L["alku"] - 1
    rivit = ["%s viikko %s..%s" % (nimi, max(alku_vk, L["aloitus"]), loppu)]
    if L["dca"] is None:
        rivit.append("Alusta: salkku %s %%, kuukausiosto ei saatavilla" % fi_etumerkki(100 * tuotto))
    else:
        d = L["dca"][1]
        voittaja = "salkku" if tuotto > d else ("kuukausiosto" if d > tuotto else "tasan")
        rivit.append("Alusta: salkku %s %%, kuukausiosto %s %% -> edell\u00e4: %s" % (
            fi_etumerkki(100 * tuotto), fi_etumerkki(100 * d), voittaja))
    if pahin is None:
        rivit.append("Pahin p\u00e4iv\u00e4: ei p\u00e4ivi\u00e4 viikolla")
    else:
        rivit.append("Pahin p\u00e4iv\u00e4: %s %s %% (%s \u20ac)" % (pahin[0], fi_etumerkki(100 * pahin[1]), fi_etumerkki(pahin[2])))
    rivit.append("Kauppam\u00e4\u00e4r\u00e4raja (%d/pv) tuli vastaan: %d kertaa viikolla, %d alusta" % (
        rajat.MAX_KAUPPOJA_PAIVA, osumat_vk, osumat))
    return "\n".join(rivit)


def main(argv=None, laheta=None):
    ap = argparse.ArgumentParser(description="Salkun paivaraportti (vain luku)")
    ap.add_argument("--salkku-db", required=True)
    ap.add_argument("--nimi", default=None, help="oletus: kannan nimi ilman salkku_-etuliitetta")
    ap.add_argument("--markkina", default=None, help="oletus config.DB_POLKU")
    ap.add_argument("--paiva", default=None, help="YYYY-MM-DD, oletus viimeisin ajettu paiva")
    ap.add_argument("--viikko", action="store_true", help="lisaa viikkoyhteenveto")
    ap.add_argument("--immutable", action="store_true", help="vain luku -kopio (esim. /var/lib/claude-jono/kauppa)")
    ap.add_argument("--tg-env", default="/srv/kauppa/.env")
    ap.add_argument("--ei-tg", action="store_true")
    a = ap.parse_args(argv)
    nimi = a.nimi or os.path.splitext(os.path.basename(a.salkku_db))[0].replace("salkku_", "")
    if a.markkina is None:
        import config
        a.markkina = config.DB_POLKU
    try:
        sal = avaa_ro(a.salkku_db, a.immutable)
        markkina = avaa_ro(a.markkina, a.immutable)
        teksti = paivaraportti(nimi, luvut(sal, markkina, a.paiva))
        if a.viikko:
            teksti += "\n\n" + viikkoyhteenveto(sal, markkina, nimi, a.paiva)
    except (Raporttivirhe, sqlite3.Error, ValueError) as e:
        print("Salkkuraportti (%s): VIRHE %s" % (nimi, type(e).__name__))
        return 2
    print(teksti)
    if not a.ei_tg:
        if laheta is None:
            import llm
            import notify
            try:
                env = llm.lue_env(a.tg_env)
            except llm.LLMVirhe as e:
                print("Telegram: ei lahetetty (%s)" % type(e).__name__)
                return 1
            laheta = lambda t: notify.laheta(t, env)
        if not laheta(teksti):
            print("Telegram: lahetys epaonnistui")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
