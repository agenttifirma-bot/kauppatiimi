"""Aktiivisten tapojen paivatuottojen eron tilastollinen arvio passiivisiin.

Vain luku, stdlib. Kayttaa saman paketin seuranta.py:n laskentaa. Ei sijoitusneuvo.
Kaytto (repon juuresta, ilman -I-kiertotieta):
  python3 -m analyysi.seuranta.arvio [kauppa-hakemisto] [--loppu YYYY-MM-DD] [--toistoja N] [--lohko N]
Oletushakemisto /var/lib/claude-jono/kauppa.

Menetelma: paivakohtainen ero d_t = r_aktiivinen,t - r_passiivinen,t.
Pyorea lohkobootstrap (kiintea siemen) keskiarvolle, 95 %:n luottamusvali
(2,5 % ja 97,5 % persentiilit). "Erottuu" vain jos vali ei sisalla nollaa
JA paivia on vahintaan MIN_PAIVAT_PAATELMA. Muuten "ei erotu" tai "data ei riita".
"""
import random
import sys
from datetime import date

from . import seuranta as s

SIEMEN = 1
TOISTOJA = 2000
LOHKO = 4
MIN_PAIVAT_PAATELMA = 90
MIN_PAIVAT_VALI = 10


def bootstrap_vali(x, siemen=SIEMEN, toistoja=TOISTOJA, lohko=LOHKO, taso=0.95):
    """Pyorea lohkobootstrap keskiarvolle. Palauttaa (alaraja, ylaraja)."""
    if toistoja < 1000:
        raise ValueError("toistoja oltava vahintaan 1000")
    n = len(x)
    if n < 1:
        raise ValueError("tyhja aineisto")
    lohko = max(1, min(lohko, n))
    rng = random.Random(siemen)
    ka = []
    for _ in range(toistoja):
        v = []
        while len(v) < n:
            i = rng.randrange(n)
            v += [x[(i + j) % n] for j in range(lohko)]
        ka.append(sum(v[:n]) / n)
    ka.sort()
    a = (1 - taso) / 2
    return ka[int(a * toistoja)], ka[int((1 - a) * toistoja) - 1]


def paatelma(vali, paivia):
    if vali is None or paivia < MIN_PAIVAT_PAATELMA:
        return "data ei riit\u00e4"
    return "erottuu" if (vali[0] > 0 or vali[1] < 0) else "ei erotu"


def arvioi(hakemisto, toistoja=TOISTOJA, lohko=LOHKO, loppu=None):
    avaus, sulku = s.lue_btc(hakemisto)
    data = {n: s.lue_salkku(hakemisto, n) for n in s.SALKUT}
    a = max(r[0][0] for _, r in data.values())
    b = min(r[-1][0] for _, r in data.values())
    if loppu is not None:
        b = min(b, loppu)
    jakso = list(s.paivat(a, b))
    if any(s.ms(p) not in sulku or s.ms(p) not in avaus for p in jakso):
        raise ValueError("BTC-hinta puuttuu")
    bh = s.passiivi_bh(jakso, avaus, sulku)
    era = s.passiivi_era(jakso, avaus, sulku)
    sv, talletettu, sr = s.passiivi_saasto(jakso, avaus, sulku)
    pas = [("BTC osta ja pida", s.paivatuotot(bh), bh[-1] - 1),
           ("Kuukausiosto, p\u00e4\u00e4oman jako erin", s.paivatuotot(era), era[-1] - 1),
           ("Kuukausiosto, jatkuva s\u00e4\u00e4st\u00f6", sr, sv[-1] / talletettu - 1)]
    rivit = []
    for nimi in s.SALKUT:
        alku, rr = data[nimi]
        arv = dict(rr)
        v = [alku] + [arv[p] for p in jakso]
        r = s.paivatuotot(v)
        tuotto = v[-1] / v[0] - 1
        for pn, pr, pt in pas:
            d = [x - y for x, y in zip(r, pr)]
            vali = bootstrap_vali(d, toistoja=toistoja, lohko=lohko) if len(d) >= MIN_PAIVAT_VALI else None
            rivit.append({"tapa": nimi, "vs": pn, "ero_kum": tuotto - pt,
                          "ka": sum(d) / len(d), "vali": vali, "paivia": len(d),
                          "paatelma": paatelma(vali, len(d))})
    return {"alku": a, "loppu": b, "paivia": len(jakso), "rivit": rivit}


def muotoile(t):
    out = ["Jakso %s .. %s, p\u00e4ivi\u00e4 %d (p\u00e4\u00e4telm\u00e4\u00e4n vaaditaan v\u00e4hint\u00e4\u00e4n %d)" % (
        t["alku"], t["loppu"], t["paivia"], MIN_PAIVAT_PAATELMA),
        "| tapa | vertailu | kumulatiivinen ero | keskiero pp/pv | 95 %:n v\u00e4li pp/pv | p\u00e4\u00e4telm\u00e4 |",
        "|---|---|---|---|---|---|"]
    for r in t["rivit"]:
        v = "ei lasketa (alle %d pv)" % MIN_PAIVAT_VALI if r["vali"] is None else \
            "[%+.3f; %+.3f]" % (r["vali"][0] * 100, r["vali"][1] * 100)
        out.append("| %s | %s | %+.2f pp | %+.3f | %s | %s |" % (
            r["tapa"], r["vs"], r["ero_kum"] * 100, r["ka"] * 100, v, r["paatelma"]))
    return "\n".join(out)


def main(argv):
    h, toistoja, lohko, loppu, i = s.OLETUS_HAKEMISTO, TOISTOJA, LOHKO, None, 0
    while i < len(argv):
        if argv[i] == "--toistoja":
            toistoja = int(argv[i + 1]); i += 2
        elif argv[i] == "--loppu":
            loppu = date.fromisoformat(argv[i + 1]); i += 2
        elif argv[i] == "--lohko":
            lohko = int(argv[i + 1]); i += 2
        else:
            h = argv[i].rstrip("/"); i += 1
    try:
        print(muotoile(arvioi(h, toistoja, lohko, loppu)))
    except (s.sqlite3.Error, ValueError, KeyError, OSError, IndexError) as e:
        print("virhe: " + type(e).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
