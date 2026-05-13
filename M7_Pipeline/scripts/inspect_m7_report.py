"""inspect_m7_report.py — 抓 nt-net2 m7 report 一頁 HTML，分析 table 結構

目的：找出 fetch_m7_report_playwright.py 為什麼抓不到 five_level_detail / 抓亂 high_machines

用法：
  1. Chrome 9222 開著、登入過 nt-net2
  2. python scripts\\inspect_m7_report.py [--eidh 317234]
  3. 看 outputs/m7_report_inspect_{eidh}.html 跟 .json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--eidh", default="317234")
    p.add_argument("--cdp-port", type=int, default=9222)
    args = p.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] pip install playwright")
        sys.exit(1)

    eidh = args.eidh
    url = f"http://nt-net2/MTM/Report/M7FiveLevelReport.aspx?eidh={eidh}"
    print(f"[1] navigating to {url}")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://localhost:{args.cdp_port}")
        context = browser.contexts[0]
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            import time
            time.sleep(2)

            # Dump HTML
            html = page.content()
            html_file = OUT_DIR / f"m7_report_inspect_{eidh}.html"
            html_file.write_text(html, encoding="utf-8")
            print(f"[2] HTML → {html_file} ({html_file.stat().st_size:,} bytes)")

            # Dump table structure
            tables_info = page.evaluate("""() => {
                const out = [];
                const tbls = document.querySelectorAll('table');
                tbls.forEach((tbl, i) => {
                    const rows = tbl.querySelectorAll('tr');
                    const cellCounts = [];
                    let firstRowText = '';
                    let secondRowText = '';
                    rows.forEach((r, j) => {
                        const cells = r.querySelectorAll('td, th');
                        cellCounts.push(cells.length);
                        if (j === 0) firstRowText = (r.innerText || '').slice(0, 200);
                        if (j === 1) secondRowText = (r.innerText || '').slice(0, 200);
                    });
                    const innerText = (tbl.innerText || '').slice(0, 300);
                    out.push({
                        idx: i,
                        rows: rows.length,
                        cellCounts: cellCounts.slice(0, 10),
                        firstRow: firstRowText,
                        secondRow: secondRowText,
                        innerTextHead: innerText,
                        // 找特徵字
                        hasFiveLevel: /五階層|FiveLevel|FIVE LEVEL/i.test(tbl.innerText),
                        hasHighMachine: /高階成本|High Machine|高階設備/i.test(tbl.innerText),
                        hasCustomMachine: /客製化|Customization/i.test(tbl.innerText),
                        hasFlags: /有此項|此項目|None|無/i.test(tbl.innerText.slice(0, 500)),
                    });
                });
                return out;
            }""")

            json_file = OUT_DIR / f"m7_report_inspect_{eidh}.json"
            json_file.write_text(json.dumps(tables_info, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[3] tables structure → {json_file}")

            # Print summary
            print(f"\n[summary] {len(tables_info)} tables found")
            for t in tables_info:
                flags = []
                if t["hasFiveLevel"]: flags.append("五階")
                if t["hasHighMachine"]: flags.append("高階")
                if t["hasCustomMachine"]: flags.append("客製")
                if t["hasFlags"]: flags.append("flags")
                tag = f" [{','.join(flags)}]" if flags else ""
                print(f"  table[{t['idx']}] rows={t['rows']:3} cells={t['cellCounts']}{tag}")
                if flags:
                    print(f"    head: {t['innerTextHead'][:150]!r}")
        finally:
            page.close()


if __name__ == "__main__":
    main()
