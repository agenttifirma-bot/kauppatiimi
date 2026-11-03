"""Kielimalli riskivahtina: saantopohjainen ydin (esim. saantosalkku.py:n strategia) paattaa kaupat, malli saa vain PIENENTAA tai ESTAA ostoja.
Suodatin ENNEN salkkua (kuten konsensus.py ja kynnys.py): salkku.py, riskivahti.py ja rajat.py ovat koskemattomia.
OLETUS POIS: toimii vain jos KAUPPA_LLM_VETO=1.
- Malli ei voi lisata kolikoita, kasvattaa ostoa eika estaa myyntia (myynti pienentaa riskia).
- Vastaus: {"veto": {"SOLUSDT": 0.0-1.0}, "perustelu": "max 500 merkkia"}; kerroin k: uusi tavoite = nyky + k * (ytimen tavoite - nyky).
- Veto ja perustelu kirjataan lokiin (veto_loki-taulu paperisalkun kannassa).
- Fail closed: LLM-virhe, kelvoton vastaus tai paivakatto -> kaikki ytimen ostot estetaan, myynnit tehdaan.
- Kutsuja enintaan 1 / paiva ja vain jos ytimella on ostoja; kulut kirjataan llm_kutsut-tauluun, jolloin rajat.MAX_LLM_KUTSUJA_PAIVA pitaa."""
import json
import os

import agentit
import konsensus
import llm
import paiva as pv
import rajat
import taulukko

TOLERANSSI = konsensus.TOLERANSSI
KUTSUT_PER_PAIVA = 1
ROOLI = "veto"

VAHTI = """You are the RISK GUARD of a paper-trading team. A rule-based core has already decided the trades; you cannot change its rules.
You receive the data table, the current holdings and the list of BUYS the core wants to make today.
You may only REDUCE or BLOCK those buys. You cannot add coins, cannot increase a buy and cannot stop sells.
Look for: anomalies visible in the numbers (extreme r7, funding spikes, very high vol30), concentration, correlated positions, missing data (n/a values), a drawdown already underway. Costs are about 0.2 % per trade.
If nothing is wrong, approve everything (empty veto). Use ONLY numbers in the <data> block; never invent numbers.
Output exactly ONE JSON object and nothing else:
{"veto": {"SYMBOL": multiplier 0.0-1.0}, "perustelu": "max 500 chars"}
multiplier 0.0 blocks the buy, 0.5 halves it, 1.0 approves. Symbols not listed are approved."""


class Vetovirhe(Exception):
    pass


def kaytossa(env=None):
    return (os.environ if env is None else env).get("KAUPPA_LLM_VETO") == "1"


def ostot(nyky, ydin, tol=TOLERANSSI):
    """{symbol: (nyky, ydin)} niille, joille ydin haluaa lisata yli toleranssin."""
    return {s: (nyky.get(s, 0.0), w) for s, w in ydin.items() if w - nyky.get(s, 0.0) > tol}


def jasenna(teksti, ostolista):
    """(veto {symbol: 0..1}, perustelu). Nostaa Vetovirhe jos vastaus on kelvoton. Kerroin yli 1 hylataan; muiden kuin ostolistan kolikoiden veto ohitetaan."""
    try:
        o = agentit.pura_json(teksti)
    except agentit.Vastausvirhe as e:
        raise Vetovirhe(type(e).__name__)
    v = o.get("veto", {})
    if not isinstance(v, dict):
        raise Vetovirhe("veto ei ole olio")
    veto = {}
    for s, k in v.items():
        if s not in ostolista:
            continue
        if isinstance(k, bool) or not isinstance(k, (int, float)) or not 0.0 <= k <= 1.0:
            raise Vetovirhe("kerroin virheellinen")
        veto[s] = float(k)
    return veto, str(o.get("perustelu", ""))[:500]


def sovella(nyky, ydin, veto):
    """Ytimen tavoitepainot vedon jalkeen. Myynnit ja pidot ennallaan; ostot nyky + k*(ydin-nyky), 0 <= k <= 1."""
    ulos = {}
    for s in set(nyky) | set(ydin):
        c, t = nyky.get(s, 0.0), ydin.get(s, 0.0)
        if t - c > TOLERANSSI and s in veto:
            t = c + min(1.0, max(0.0, veto[s])) * (t - c)
        if t > 1e-12:
            ulos[s] = t
    return ulos


def esta_kaikki(nyky, ydin):
    return sovella(nyky, ydin, {s: 0.0 for s in ydin})


def _loki(sal, paiva, malli, tulos, veto, perustelu, ostolista):
    sal.execute("CREATE TABLE IF NOT EXISTS veto_loki (paiva TEXT PRIMARY KEY, malli TEXT, tulos TEXT, veto TEXT, perustelu TEXT, ostot TEXT)")
    sal.execute("INSERT OR REPLACE INTO veto_loki VALUES (?,?,?,?,?,?)",
                (paiva.isoformat(), malli, tulos, json.dumps(veto, sort_keys=True), perustelu,
                 json.dumps({s: list(v) for s, v in ostolista.items()}, sort_keys=True)))
    sal.commit()


def suodata(sal, markkina, paiva, ydin, sallitut, malli, env, hae=None, paalla=None):
    """ydin: ytimen tavoitepainot {symbol: paino} (tai None). Pois paalta -> ydin sellaisenaan (ei kutsuja, ei lokia).
    Paalla: palauttaa vedon jalkeiset painot. Mika tahansa epavarmuus -> ostot estetty.
    malli: LiteLLM-nimi, vain rajat.MALLIT-arvoista; env: {LLM_BASE_URL, LLM_API_KEY}; hae: testeissa mockattu HTTP-kutsu."""
    if not (kaytossa() if paalla is None else paalla):
        return ydin
    if not isinstance(ydin, dict) or malli not in rajat.MALLIT.values():
        return {}                                   # ei ydinta tai ei sallittu malli: ei kauppoja
    nyky = konsensus.nykypainot(sal, markkina, paiva)
    if nyky is None:
        return ydin   # hinta puuttuu: salkku kasittelee tilanteen omilla saannoillaan (Datavirhe omistetulle)
    ostolista = ostot(nyky, ydin)
    if not ostolista:
        return ydin                                 # ei ostoja -> ei mitaan vahdittavaa, ei kutsua
    if pv._kutsut_tanaan(sal, paiva) + KUTSUT_PER_PAIVA > rajat.MAX_LLM_KUTSUJA_PAIVA:
        _loki(sal, paiva, malli, "kutsukatto", {}, "", ostolista)
        return esta_kaikki(nyky, ydin)
    veto, perustelu, tulos = {}, "", "ok"
    try:
        teksti, _ = taulukko.rakenna(markkina, paiva)
        rivit = "\n".join("%s: %.1f %% -> %.1f %%" % (s, 100 * a, 100 * b) for s, (a, b) in sorted(ostolista.items()))
        viestit = [{"role": "system", "content": VAHTI},
                   {"role": "user", "content": "%s\n<salkku>\n%s\n</salkku>\n<ostot>\n%s\n</ostot>"
                    % (teksti, pv.omistukset_teksti(sal, markkina, paiva), rivit)}]
        vastaus, kaytto = llm.kysy(viestit, malli, env, hae)
        pv._kirjaa_kutsu(sal, paiva, ROOLI, malli, kaytto)
        veto, perustelu = jasenna(vastaus, ostolista)
    except (llm.LLMVirhe, Vetovirhe) as e:
        tulos, perustelu, veto = "virhe", type(e).__name__, {}
    uudet = esta_kaikki(nyky, ydin) if tulos == "virhe" else sovella(nyky, ydin, veto)
    _loki(sal, paiva, malli, tulos, veto, perustelu, ostolista)
    return uudet
