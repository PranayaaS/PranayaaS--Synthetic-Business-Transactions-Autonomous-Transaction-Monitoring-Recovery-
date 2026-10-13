"""Cache the dashboard's CDN assets locally so the demo works with no internet.

Downloads Tailwind (Play CDN build), Chart.js and the Google Fonts used by the dashboard
(Inter, JetBrains Mono, Material Symbols) into monitor/static/vendor/. Pages load these local
copies first and fall back to the CDN when they are missing. Run once while online:

    python vendor_assets.py
"""
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "monitor" / "static" / "vendor"
FONTS = VENDOR / "fonts"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}
SCRIPTS = {
    "tailwind.js": "https://cdn.tailwindcss.com/3.4.16",
    "chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
}
FONT_CSS = [
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap",
    "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200",
]


def main():
    FONTS.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=UA, follow_redirects=True, timeout=60) as c:
        for name, url in SCRIPTS.items():
            r = c.get(url)
            r.raise_for_status()
            (VENDOR / name).write_bytes(r.content)
            print(f"  {name:<20} {len(r.content) / 1024:8.1f} KB  <- {url}")
        css_out, n_files = [], 0
        for url in FONT_CSS:
            css = c.get(url).raise_for_status().text
            for font_url in sorted(set(re.findall(r"url\((https://[^)]+)\)", css))):
                n_files += 1
                fname = f"f{n_files:03d}_" + re.sub(r"[^A-Za-z0-9_.-]", "_", font_url.split("/")[-1])
                data = c.get(font_url).raise_for_status().content
                (FONTS / fname).write_bytes(data)
                css = css.replace(font_url, f"fonts/{fname}")
            css_out.append(css)
        (VENDOR / "fonts.css").write_text("\n".join(css_out), encoding="utf-8")
        n = len(list(FONTS.iterdir()))
        size = sum(f.stat().st_size for f in FONTS.iterdir()) / 1024 / 1024
        print(f"  fonts.css + {n} font files ({size:.1f} MB)")
    print(f"Done. Assets cached in {VENDOR}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.exit(f"Asset download failed ({e}). The dashboard still works online via the CDN.")
