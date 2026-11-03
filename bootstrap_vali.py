"""Ympyrälohkobootstrap kahden paivatuottosarjan erotukselle (vain stdlib, ei tietokantaa).

Sarjat annetaan parametrina. Parillinen otanta: molemmat sarjat saavat joka toistossa samat
indeksit. Vali on [p5, p95] eli 90 %:n vali. Katso tulos 2026-11-02-26.
"""
import math
import random

VUOSI = 365


def tuotot(arvot):
    """Salkun arvosarjasta paivatuotot."""
    return [arvot[i + 1] / arvot[i] - 1 for i in range(len(arvot) - 1)]


def kokonaistuotto(r):
    v = 1.0
    for x in r:
        v *= 1 + x
    return v - 1


def loki_keskiarvo(r):
    return sum(math.log1p(x) for x in r) / len(r)


def enimmaistappio(r):
    v = huippu = 1.0
    m = 0.0
    for x in r:
        v *= 1 + x
        huippu = max(huippu, v)
        m = max(m, 1 - v / huippu)
    return m


def persentiili(arvot, p):
    """Lineaarisesti interpoloitu persentiili, p valilla 0..1."""
    s = sorted(arvot)
    k = (len(s) - 1) * p
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def indeksit(n, lohko, rng):
    """n indeksia: lohkon mittaisia ympyrajaksoja, alkukohta tasajakaumasta."""
    if n <= 0 or lohko <= 0:
        raise ValueError("n ja lohko pitaa olla positiivisia")
    ulos = []
    while len(ulos) < n:
        a = rng.randrange(n)
        ulos.extend((a + j) % n for j in range(lohko))
    return ulos[:n]


def suureet(r):
    """Kolme tilastosuuretta: kokonaistuotto, vuositettu log-tuotto, enimmaistappio."""
    return {"tuotto": kokonaistuotto(r), "loki": loki_keskiarvo(r) * VUOSI, "mdd": enimmaistappio(r)}


def ero(a, b):
    sa, sb = suureet(a), suureet(b)
    return {k: sa[k] - sb[k] for k in sa}


def vali(arvot):
    return (persentiili(arvot, 0.05), persentiili(arvot, 0.95))


def bootstrap_ero(a, b, lohko=30, toistoja=2000, siemen=1):
    """Sarjojen a - b erotus ja 90 %:n vali jokaiselle suureelle.

    Palauttaa {suure: {"piste", "mediaani", "vali": (p5, p95), "p_positiivinen"}}.
    """
    if len(a) != len(b) or not a:
        raise ValueError("sarjojen pitaa olla yhta pitkia ja ei-tyhjia")
    rng = random.Random(siemen)
    n = len(a)
    otokset = {"tuotto": [], "loki": [], "mdd": []}
    for _ in range(toistoja):
        ix = indeksit(n, lohko, rng)
        e = ero([a[i] for i in ix], [b[i] for i in ix])
        for k in otokset:
            otokset[k].append(e[k])
    piste = ero(a, b)
    return {k: {"piste": piste[k], "mediaani": persentiili(v, 0.5), "vali": vali(v),
                "p_positiivinen": sum(x > 0 for x in v) / len(v)} for k, v in otokset.items()}
