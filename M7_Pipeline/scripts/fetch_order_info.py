"""fetch_order_info.py — 從 nt-sps ordersite 抓 Product Category (= gender)

URL: http://nt-sps/ordersite/
流程：
  1. CDP attach 到本機 Chrome (port 9222)
  2. 每筆開新 tab → navigate → 等 iframe load
  3. fill Style input (在 iframe) + click Search (a:has-text)
  4. ASP.NET postback → re-find target frame
  5. click result style link → 開新 detail tab
  6. 抽 Order Information 欄位（Product Category = gender 來源）

需要：
  pip install playwright
  Chrome 開 port 9222 + 登入過 nt-sps
    chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\chrome_debug_profile"

用法：
  python scripts\\fetch_order_info.py [--limit 5] [--reset]

讀 style# from m7_report.jsonl，每筆 ~10 sec，1180 約 3 hr。
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
OUT = DL / "data" / "ingest" / "metadata" / "order_info.jsonl"
STATE = DL / "data" / "ingest" / "metadata" / ".order_info_state"

ORDERSITE_URL = "http://nt-sps/ordersite/#/"

INPUT_SEL = (
    'input[placeholder*="Style" i], input[name*="style" i], '
    'input[id*="style" i], input[ng-model*="style" i]'
)


def find_target_frame(page):
    """找 ordersite iframe（含 Style input）+ 確認 frame alive"""
    try:
        if page.query_selector(INPUT_SEL):
            return page
    except Exception:
        pass
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            frame.evaluate("() => 1")
            if frame.query_selector(INPUT_SEL):
                return frame
        except Exception:
            continue
    return None


def ensure_ordersite_loaded(page, debug=False):
    """每筆都 navigate 確保 clean state"""
    if debug:
        print(f"  [debug] navigating")
    try:
        page.goto("about:blank", wait_until="domcontentloaded", timeout=10000)
    except Exception:
        pass
    try:
        page.goto(ORDERSITE_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"  [warn] navigate fail: {str(e)[:80]}")
        return None
    for _ in range(15):
        target = find_target_frame(page)
        if target:
            try:
                target.evaluate("() => 1")
                return target
            except Exception:
                pass
        time.sleep(1.0)
    return None


def scrape_one(page, style_no, timeout_ms=20000, debug=False):
    out = {"style_no": style_no}
    context = page.context

    target = ensure_ordersite_loaded(page, debug=debug)
    if not target:
        out["_status"] = "ordersite_not_loaded"
        return out

    # Fill Style input + dispatch input event (Angular)
    try:
        sl = target.locator(INPUT_SEL).first
        sl.click()
        sl.fill("")
        sl.fill(style_no)
        sl.evaluate("el => { el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }")
    except Exception as e:
        out["_status"] = f"fill_fail:{str(e)[:50]}"
        return out

    # Click Search button — 用 evaluate 找最右下那顆 Search<a>，加臨時 id 給 Playwright click
    search_clicked = False
    try:
        info = target.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('a, button, input[type=submit], input[type=button]'));
            const cands = els.filter(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return false;
                const txt = ((el.innerText || el.value || '') + '').trim();
                if (!txt || !/Search/i.test(txt) || txt.length > 30) return false;
                return true;
            });
            if (cands.length === 0) return null;
            cands.sort((a, b) => {
                const ra = a.getBoundingClientRect();
                const rb = b.getBoundingClientRect();
                return (rb.y + rb.x) - (ra.y + ra.x);
            });
            const el = cands[0];
            el.id = '__playwright_search_btn__';
            return {tag: el.tagName, text: ((el.innerText||el.value||'')+'').trim(), total: cands.length};
        }""")
        if info:
            target.locator("#__playwright_search_btn__").click(timeout=5000)
            search_clicked = True
            if debug:
                print(f"  [debug] clicked Search: {info}")
    except Exception as e:
        if debug:
            print(f"  [debug] search fail: {str(e)[:80]}")

    if not search_clicked:
        out["_status"] = "search_btn_not_found"
        return out

    # ASP.NET postback → re-find target
    time.sleep(1.5)
    target = find_target_frame(page)
    if not target:
        for _ in range(5):
            time.sleep(1.0)
            target = find_target_frame(page)
            if target:
                break
    if not target:
        out["_status"] = "frame_lost_after_search"
        return out

    # 等 result table
    try:
        target.wait_for_selector("text=/\\d+ results?/i", timeout=8000)
    except Exception:
        pass
    time.sleep(0.5)

    # 找 result style link
    LINK_SEL = f'a:text-is("{style_no}"), a:has-text("{style_no}")'
    try:
        link_loc = target.locator(LINK_SEL).first
        link_loc.wait_for(state="visible", timeout=8000)
    except Exception:
        out["_status"] = "no_result"
        return out

    # Click → 開新 detail tab
    try:
        with context.expect_page(timeout=timeout_ms) as new_page_info:
            link_loc.click()
        detail_page = new_page_info.value
        detail_page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        time.sleep(1.5)
    except Exception:
        time.sleep(2)
        detail_page = page

    # 抽 Order Information table（4-col layout: label|val|label|val）
    js = """() => {
        const result = {};
        const trs = document.querySelectorAll('tr, div.row');
        for (const tr of trs) {
            const cells = tr.querySelectorAll('td, th, div.col, div.col-md-3, div.col-md-2');
            for (const stride of [2, 4]) {
                for (let i = 0; i + 1 < cells.length; i += stride) {
                    const label = (cells[i].innerText || '').trim();
                    const value = (cells[i+1].innerText || '').trim();
                    if (label && value && label.length < 40 && label.length > 1
                        && !result[label] && !label.includes('\\n')) {
                        result[label] = value;
                    }
                }
            }
        }
        const dts = document.querySelectorAll('dt');
        for (const dt of dts) {
            const dd = dt.nextElementSibling;
            if (dd && dd.tagName === 'DD') {
                const k = dt.innerText.trim();
                const v = dd.innerText.trim();
                if (k && v && !result[k]) result[k] = v;
            }
        }
        return result;
    }"""
    raw = detail_page.evaluate(js)
    try:
        if detail_page is not page:
            detail_page.close()
    except Exception:
        pass

    # 對應 schema
    label_map = {
        "Order Status": "order_status",
        "Style": "style",
        "Style No": "style_no_mom",
        "Cust Style No": "cust_style_no",
        "Customer": "customer_mom",
        "Subgroup": "subgroup_mom",
        "Brand": "brand_mom",
        "Country": "country",
        "Shipper": "shipper",
        "Maker": "maker",
        "1st EXP Date": "exp_date_first",
        "CRFP Date": "crfp_date",
        "Order Qty": "order_qty",
        "Season": "season_mom",
        "Woven/Knit": "woven_knit",
        "Order Priority": "order_priority",
        "Product Category": "product_category",   # ★ gender 來源
        "Product Item": "product_item",
        "Product Line": "product_line",
        "Program": "program_mom",
        "Trade Type To Factory": "trade_type",
        "IE": "ie_text",
        "Index No": "index_no_mom",
        "FAB YY": "fab_yy",
        "Fabric": "fabric_full",
        "Special Process": "special_process",
        "Special Machine": "special_machine",
        "Construction": "construction_text",
        "Sales": "sales_text",
    }
    for label, key in label_map.items():
        if label in raw:
            out[key] = raw[label]
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--cdp-port", type=int, default=9222)
    p.add_argument("--max-seconds", type=int, default=10800)
    args = p.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] pip install playwright")
        sys.exit(1)

    if args.reset:
        if STATE.exists():
            STATE.unlink()
        if OUT.exists():
            OUT.unlink()

    # Load styles
    styles = set()
    for line in open(M7_REPORT, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        s = (r.get("style_no") or "").strip()
        if s and s not in ("Style", ""):
            styles.add(s)
    styles = sorted(styles)
    print(f"[load] {len(styles)} unique style# from m7_report")

    next_idx = 0
    if STATE.exists():
        next_idx = int(STATE.read_text().strip())
    if args.limit:
        styles = styles[: args.limit]
    if next_idx >= len(styles):
        print(f"═══ ALL DONE ═══ ({next_idx} done)")
        return

    print(f"[batch] {next_idx}..{len(styles)-1} of {len(styles)}")
    t0 = time.time()
    n_ok = n_err = n_real = 0
    open_mode = "a" if next_idx > 0 and OUT.exists() else "w"

    with sync_playwright() as pw:
        cdp_url = f"http://localhost:{args.cdp_port}"
        print(f"[browser] CDP attach to {cdp_url}")
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]

        with open(OUT, open_mode, encoding="utf-8") as fout:
            i = next_idx
            while i < len(styles):
                if time.time() - t0 >= args.max_seconds:
                    print(f"  [!] hit {args.max_seconds}s budget at {i}, stopping")
                    break
                style = styles[i]
                page = context.new_page()
                try:
                    data = scrape_one(page, style, debug=(i < next_idx + 3))
                    if data.get("product_category"):
                        n_real += 1
                    fout.write(json.dumps(data, ensure_ascii=False) + "\n")
                    fout.flush()
                    n_ok += 1
                    if i % 20 == 0 or i == next_idx:
                        print(
                            f"  [{i}/{len(styles)}] {style} → "
                            f"category={data.get('product_category','?')[:15]} "
                            f"customer={(data.get('customer_mom') or '?')[:18]} "
                            f"(real={n_real}, ok={n_ok})"
                        )
                except Exception as e:
                    print(f"  [!] {style}: {str(e)[:100]}")
                    n_err += 1
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                STATE.write_text(str(i + 1))
                i += 1

    print(f"\n[done] {n_ok} ok, {n_err} err, {n_real} 有 product_category")
    print(f"[output] {OUT}")


if __name__ == "__main__":
    main()
