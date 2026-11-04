"""Osakeindeksin paivahinnat ilmaisesta lahteesta ilman tunnuksia (Yahoo Finance chart-rajapinta, epavirallinen).
Tallentaa CSV:n paiva,open,close. Ei kaytossa tuotantoajossa eika testeissa (verkko); vain kerran ajettava datanhaku.
Indeksi on hintaindeksi (^GSPC): osingot eivat ole mukana. Kaytto: python3 indeksidata.py ^GSPC polku.csv"""
import csv
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MAX_TAVUA = 10_000_000


def jasenna(teksti):
    """Yahoo chart-JSON -> [(date, open, close)] aikajarjestyksessa; puuttuvat (None) rivit ohitetaan."""
    d = json.loads(teksti)
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    ulos = {}
    for ts, o, c in zip(r["timestamp"], q["open"], q["close"]):
        if o is None or c is None:
            continue
        ulos[datetime.fromtimestamp(ts, timezone.utc).date()] = (float(o), float(c))
    return [(p, o, c) for p, (o, c) in sorted(ulos.items())]


def hae(symboli, alue="10y"):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d" % (urllib.parse.quote(symboli), alue)
    pyynto = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(pyynto, timeout=30) as v:
        return jasenna(v.read(MAX_TAVUA).decode("utf-8"))


def kirjoita(rivit, polku):
    with open(polku, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["paiva", "open", "close"])
        for p, o, c in rivit:
            w.writerow([p.isoformat(), repr(o), repr(c)])


def lue(polku):
    """CSV -> {"open": {date: x}, "close": {date: x}}."""
    from datetime import date
    avaus, sulku = {}, {}
    with open(polku, newline="") as f:
        for r in csv.DictReader(f):
            p = date.fromisoformat(r["paiva"])
            avaus[p], sulku[p] = float(r["open"]), float(r["close"])
    return {"open": avaus, "close": sulku}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("kaytto: indeksidata.py SYMBOLI polku.csv")
        sys.exit(2)
    try:
        rivit = hae(sys.argv[1])
        kirjoita(rivit, sys.argv[2])
    except (OSError, ValueError, KeyError, IndexError) as e:
        print("virhe:", type(e).__name__)
        sys.exit(1)
    print("%d rivia, %s .. %s" % (len(rivit), rivit[0][0], rivit[-1][0]))
