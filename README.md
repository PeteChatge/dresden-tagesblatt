# Dresden-Tagesblatt

Gewichtete Tageszeitung nach Prio-Regeln V1. Kein Neutral-Etikett.

Raster: I. Stadt Dresden (detailliert), II. Umland, III. Sachsen, IV. Ost ohne Sachsen, V. West + Nachbar-Ausland.

Prio: 1) Exekutive (Polizei vor Judikative), 2) Verwaltung/Amtsblatt/DVB, 3) NIUS/Welt, 4) Ausland Nachbarn (CH, CZ, HU, SK, IT – kein RU/UA), 5) ÖRR zuletzt.

## Benutzung

```bash
python3 fetch.py            # holen + heilen (nur Standardbibliothek)
python3 fetch.py --dry-run  # nur prüfen
python3 fetch.py --alle     # auch Reserven testen
python3 fetch.py --export   # zusätzlich index-export.html bauen
```

Danach `index.html` im Browser öffnen (lädt `data/latest.json`). Für GitHub Pages `index-export.html` verwenden.

## Regeln

- Nur Kurzzusammenfassungen mit abgeschlossenem Satz + Link, keine Volltexte.
- Wertende Presse-Meldung braucht 2 Träger, Amtliches 1 Quelle mit Label Einzelquelle/amtlich.
- Demos: Rückblick verifiziert, Preview nur belegt.
- Stimmung nur Gesamtdeutschland via Sonntagsumfrage/Wahlen.
- Kleingedrucktes „Wem gehört was“ am Seitenende beachten.

## Dateien

- `index.html` – Ausgabe (statt zeitung.html), hell/dunkel, Vorlesen.
- `quellen.json` – Quellen-Pool, nur fetch.py schreibt.
- `fetch.py` – Sammeln + Absichern.
- `data/latest.json`, `data/health.json` – Ablage.
