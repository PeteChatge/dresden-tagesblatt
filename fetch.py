#!/usr/bin/env python3
"""Dresden-Tagesblatt fetch.py – gestärkt aus independent-news übernommen.

Nur Standardbibliothek. Aufgaben:
  1. quellen.json prüfen (rss + fallbacks), Gesundheit messen (ok/stale/fail/leer).
  2. Artikel holen (Titel, Link, Datum, Kurzbeschreibung) – nur Zusammenfassung,
     keine Volltexte. Sätze werden abgeschlossen (Punkt am Ende).
  3. Wetter Dresden via Open-Meteo (schlüsselfrei) holen.
  4. data/latest.json + data/health.json schreiben (mit .bak-Sicherung).
  5. Optional --export: baut index-export.html (monolithisch, JSON eingebettet)
     für GitHub Pages / Weitergabe als Einzeldatei.

Aufruf (Windows: python, Linux/Mac: python3):
  python fetch.py              # holen + heilen
  python fetch.py --dry-run    # nur prüfen
  python fetch.py --alle       # auch Reserven testen
  python fetch.py --export     # zusätzlich Einzeldatei-Export bauen
"""
import json, sys, ssl, re, shutil, html
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
from email.utils import parsedate_to_datetime

BASIS = Path(__file__).resolve().parent
QUELLEN_DATEI = BASIS / "quellen.json"
DATA_DIR = BASIS / "data"
LATEST_DATEI = DATA_DIR / "latest.json"
HEALTH_DATEI = DATA_DIR / "health.json"
INDEX_DATEI = BASIS / "index.html"
EXPORT_DATEI = BASIS / "index-export.html"
UA = {"User-Agent": "Mozilla/5.0 (Dresden-Tagesblatt; Redundanz-Check; +lokal)"}

DRESDEN_LAT, DRESDEN_LON = 51.05, 13.74

def parse_datum(txt):
    try:
        dt = parsedate_to_datetime(txt.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def ensure_period(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if s[-1] in ".!?:":
        return s if s[-1] in ".!?" else s[:-1].strip() + "."
    return s + "."

KURZ_LIMIT = 700  # Auszugslänge: ausführlich genug für eigenes Bild, kein Volltext

def clean_text(t: str, limit: int = KURZ_LIMIT) -> str:
    t = (t or "").replace("<![CDATA[", "").replace("]]>", "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        # Satzweise kürzen: möglichst an einem Satzende nahe dem Limit trennen,
        # damit keine Fantasie-Lücken durch abgerissene Halbsätze entstehen.
        fenster = t[:limit + 300]
        # Satzenden (Satzzeichen + Leerzeichen/Großbuchstabe/Ende) im Fenster suchen
        enden = [m.end() for m in re.finditer(r"[.!?](?=\s+[A-ZÄÖÜ„\"'(\[]|\s*$)", fenster)]
        nahe = [e for e in enden if e >= limit * 0.6]
        if nahe:
            # Nächstes Satzende ab Limit nehmen, sonst letztes davor
            nach = [e for e in nahe if e >= limit]
            t = fenster[:min(nach) if nach else max(nahe)].strip()
        else:
            cut = t[:limit].rsplit(" ", 1)[0]
            t = cut if cut else t[:limit]
    return ensure_period(t)

def hole(url: str, timeout: int = 12, max_bytes: int = 300_000) -> tuple:
    if url.startswith("CH-PROXY:"):
        raise RuntimeError("Proxy nicht aktiv")
    req = Request(url, headers=UA)
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=ctx) as r:
        ct = r.headers.get("Content-Type", "?")
        roh = r.read(max_bytes).decode("utf-8", errors="ignore")
        return r.status, ct, roh

def vermesse(roh: str):
    items = len(re.findall(r"<item[\s>]", roh)) + roh.count("<entry>")
    datums = re.findall(
        r"<(?:pubDate|lastBuildDate|updated|published|dc:date)>(.*?)</(?:pubDate|lastBuildDate|updated|published|dc:date)>",
        roh)
    neueste = None
    for d in datums[:12]:
        dt = parse_datum(d)
        if dt and (neueste is None or dt > neueste):
            neueste = dt
    return items, neueste

def extrahiere_artikel(roh: str, max_n: int = 6):
    out = []
    for m in re.finditer(r"<item[\s>](.*?)</item>", roh, re.S):
        if len(out) >= max_n:
            break
        block = m.group(1)
        def tag(nm):
            mm = re.search(rf"<{nm}[^>]*>(.*?)</{nm}>", block, re.S)
            return mm.group(1).strip() if mm else ""
        title = clean_text(tag("title"), 160)
        link = re.sub(r"\s+", "", tag("link").replace("<![CDATA[", "").replace("]]>", ""))[:500]
        # link kann in <guid> stehen
        if not link.startswith("http"):
            g = tag("guid")
            mg = re.search(r"https?://[^\s<]+", g)
            if mg:
                link = mg.group(0)
        pub = tag("pubDate") or tag("dc:date") or tag("published") or tag("updated")
        desc = clean_text(tag("content:encoded") or tag("description") or tag("summary"))
        if title and link.startswith("http"):
            out.append({"titel": title, "link": link, "datum": pub[:64], "kurz": desc})
    # Atom-Fallback
    if not out:
        for m in re.finditer(r"<entry>(.*?)</entry>", roh, re.S):
            if len(out) >= max_n:
                break
            block = m.group(1)
            tm = re.search(r"<title[^>]*>(.*?)</title>", block, re.S)
            lm = re.search(r'<link[^>]*href="([^"]+)"', block)
            pm = re.search(r"<(?:published|updated)>(.*?)</(?:published|updated)>", block, re.S)
            sm = re.search(r"<(?:summary|content)[^>]*>(.*?)</(?:summary|content)>", block, re.S)
            title = clean_text(tm.group(1) if tm else "", 160)
            link = (lm.group(1) if lm else "").strip()[:500]
            if title and link.startswith("http"):
                out.append({"titel": title, "link": link,
                            "datum": (pm.group(1).strip()[:64] if pm else ""),
                            "kurz": clean_text(sm.group(1) if sm else "")})
    return out

def hole_wetter():
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={DRESDEN_LAT}&longitude={DRESDEN_LON}"
           "&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max&timezone=Europe%2FBerlin&forecast_days=2")
    try:
        _, _, roh = hole(url, timeout=10)
        j = json.loads(roh)
        cur = j.get("current", {})
        daily = j.get("daily", {})
        txt = (f"Dresden aktuell {cur.get('temperature_2m', '?')} °C. "
               f"Heute max { (daily.get('temperature_2m_max') or ['?'])[0] } °C, "
               f"min { (daily.get('temperature_2m_min') or ['?'])[0] } °C. "
               f"Regenwahrscheinlichkeit max { (daily.get('precipitation_probability_max') or ['?'])[0] } Prozent.")
        return {"ok": True, "text": ensure_period(txt), "quelle": "Open-Meteo (CC-BY 4.0)", "raw_time": cur.get("time", "")}
    except Exception as e:
        return {"ok": False, "text": "Wetter derzeit nicht abrufbar.", "fehler": f"{type(e).__name__}: {e}"[:200]}

def pruefe(q, fresh_h, stale_h, mit_fallbacks=True):
    kands = [q["rss"]] + ((q.get("rss_fallbacks") or []) if mit_fallbacks else [])
    err = None
    for url in kands:
        try:
            http, ct, roh = hole(url)
            items, neueste = vermesse(roh)
            jetzt = datetime.now(timezone.utc)
            alter = round((jetzt - neueste).total_seconds() / 3600, 1) if neueste else None
            if items == 0:
                st = "leer"
            elif alter is None:
                st = "ok_ohne_datum"
            elif alter <= fresh_h:
                st = "ok"
            elif alter <= stale_h:
                st = "stale"
            else:
                st = "versiegelt"
            arts = extrahiere_artikel(roh, 8) if st in ("ok", "ok_ohne_datum", "stale") else []
            return {"url_ok": url, "http": http, "items": items, "neueste": neueste.isoformat() if neueste else None,
                    "alter_h": alter, "status": st, "fehler": None, "artikel": arts}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:160]}"
    return {"url_ok": None, "http": None, "items": 0, "neueste": None, "alter_h": None,
            "status": "fail", "fehler": err, "artikel": []}

def haupt():
    dry = "--dry-run" in sys.argv
    alle = "--alle" in sys.argv
    do_export = "--export" in sys.argv
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(QUELLEN_DATEI.read_text(encoding="utf-8"))
    fresh_h, stale_h = data["meta"]["quorum"]["fresh_h"], data["meta"]["quorum"]["stale_h"]
    min_g = data["meta"]["quorum"]["min_gesund_pro_gruppe"]
    quellen = data["quellen"]

    erg, artikel_ges = {}, []
    for q in quellen:
        if not q.get("aktiv") and not alle:
            erg[q["id"]] = {"status": "reserve_ruhig"}
            continue
        r = pruefe(q, fresh_h, stale_h)
        e = {"gruppe": q["gruppe"], "region": q.get("region", "?"), "tier": q["tier"],
             "aktiv": q.get("aktiv"), "rss_konfiguriert": q["rss"], **r}
        erg[q["id"]] = e
        for a in r.get("artikel", [])[:6]:
            artikel_ges.append({"quelle": q["id"], "quellen_name": q["name"],
                                "gruppe": q["gruppe"], "region": q.get("region", "?"),
                                "owner": q.get("owner", ""), **a})
        print(f"{r['status']:14} {q['id']:16} items={r['items']!s:>4} arts={len(r.get('artikel', []))} | {r['url_ok'] or r['fehler']}")

    gesund = lambda s: s in ("ok", "ok_ohne_datum")
    gruppen = {}
    for q in quellen:
        g = q["gruppe"]
        gruppen.setdefault(g, {"gesund": 0, "aktiv": 0, "mitglieder": []})
        e = erg.get(q["id"], {})
        if q.get("aktiv"):
            gruppen[g]["aktiv"] += 1
            if gesund(e.get("status")):
                gruppen[g]["gesund"] += 1
        gruppen[g]["mitglieder"].append(q["id"])
    for g, v in gruppen.items():
        v["quorum_ok"] = v["gesund"] >= min_g

    # Selbstheilung: Fallback-URL übernehmen + tote Primäre melden
    aktionen = []
    by_id = {q["id"]: q for q in quellen}
    for qid, e in erg.items():
        q = by_id.get(qid)
        if not q or not q.get("aktiv"):
            continue
        if e.get("url_ok") and e["url_ok"] != q["rss"] and gesund(e.get("status")):
            aktionen.append(f"{qid}: Fallback übernommen {e['url_ok']}")
            if not dry:
                fb = q.get("rss_fallbacks", [])
                if q["rss"] not in fb:
                    fb.insert(0, q["rss"])
                q["rss_fallbacks"] = fb
                q["rss"] = e["url_ok"]
    for g, v in gruppen.items():
        if not v["quorum_ok"]:
            aktionen.append(f"QUORUM {g}: nur {v['gesund']}/{v['aktiv']} gesund – Recherche-Bedarf")

    wetter = hole_wetter()
    print(("Wetter OK: " + wetter["text"]) if wetter["ok"] else ("Wetter FAIL: " + str(wetter.get("fehler"))))

    jetzt = datetime.now(timezone.utc).isoformat()
    latest = {"generated_at": jetzt, "hinweis": "Kurzzusammenfassungen + Link, keine Volltexte. Sätze abgeschlossen.",
              "wetter": wetter, "artikel": artikel_ges[:80],
              "stimmung": {"quelle": "Sonntagsumfrage (z. B. infratest-dimap) + Wahlergebnisse (bundeswahlleiterin.de / wahlrecht.de)",
                           "text": "Stimmungsbild nur Gesamtdeutschland, grob via Sonntagsumfrage und Wahlen. Details per Link prüfen, nicht als Fakt übernehmen."}}
    health = {"meta": {"check_zeit": jetzt, "modus": "dry-run" if dry else "fetch",
                       "fresh_h": fresh_h, "stale_h": stale_h},
              "gruppen": gruppen, "quellen": {k: {kk: vv for kk, vv in v.items() if kk != "artikel"} for k, v in erg.items()},
              "aktionen": aktionen, "wetter_ok": wetter["ok"]}

    if not dry:
        if LATEST_DATEI.exists():
            shutil.copy2(LATEST_DATEI, LATEST_DATEI.with_suffix(".json.bak"))
        if HEALTH_DATEI.exists():
            shutil.copy2(HEALTH_DATEI, HEALTH_DATEI.with_suffix(".json.bak"))
        LATEST_DATEI.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
        HEALTH_DATEI.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
        if aktionen:
            shutil.copy2(QUELLEN_DATEI, QUELLEN_DATEI.with_suffix(".json.bak"))
            data["meta"]["version"] = f"auto {datetime.now(timezone.utc).date()}"
            QUELLEN_DATEI.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGeschrieben: {LATEST_DATEI.name} ({len(artikel_ges)} Artikel), {HEALTH_DATEI.name}")
    else:
        print("\n(dry-run: nichts geschrieben)")

    print("\n--- GRUPPEN ---")
    for g, v in gruppen.items():
        print(f"[{'OK ' if v['quorum_ok'] else 'BEDARF'}] {g:18} gesund={v['gesund']}/{v['aktiv']}")

    if not dry and INDEX_DATEI.exists():
        tpl = INDEX_DATEI.read_text(encoding="utf-8")
        # Alten eingebetteten Snapshot für saubere Vorlage entfernen
        tpl_clean = re.sub(r"/\*__SNAPSHOT_START__\*/.*?/\*__SNAPSHOT_END__\*/",
                           "/*__SNAPSHOT_START__*/\n/*__SNAPSHOT_END__*/",
                           tpl, flags=re.S)
        snap = json.dumps(latest, ensure_ascii=False).replace("</", "<\\/")
        eingebettet = f"/*__SNAPSHOT_START__*/\nwindow.__SNAPSHOT__={snap};\n/*__SNAPSHOT_END__*/"
        # 1. index.html selbst auffüllen (funktioniert per Doppelklick/file://)
        out_index = tpl_clean.replace("/*__SNAPSHOT_START__*/\n/*__SNAPSHOT_END__*/", eingebettet)
        if out_index != tpl:
            shutil.copy2(INDEX_DATEI, INDEX_DATEI.with_suffix(".html.bak"))
            INDEX_DATEI.write_text(out_index, encoding="utf-8")
            print(f"Eingebettet: {INDEX_DATEI.name} (Doppelklick-fähig)")
        # 2. Monolith-Kopie für GitHub Pages / Weitergabe
        EXPORT_DATEI.write_text(out_index, encoding="utf-8")
        print(f"Export: {EXPORT_DATEI.name}")

if __name__ == "__main__":
    if not QUELLEN_DATEI.exists():
        sys.exit(f"FEHLT: {QUELLEN_DATEI}")
    haupt()
