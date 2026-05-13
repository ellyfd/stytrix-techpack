"""fetch_m7_report_playwright.py — 用 Playwright 真開瀏覽器抓 nt-net2 五階報表

跟 fetch_m7_report.py 相比：
  - 用 sync_playwright 開 headless Chrome
  - 自動帶 Windows AD SSO（Chrome 預設）
  - 等 page render 完再抓 span values

v2 (2026-05-11):
  - 加 --resume:讀 m7_report.jsonl 已有 EIDH set,自動跳過 (Q「之前跑過的不要再跑」)
  - 加 --workers N (default 4):用 ProcessPoolExecutor 起多個 Chrome instance 並行
    sequential 18,731 件 ~8 hr → 4 worker ~2 hr / 8 worker ~1 hr (看 SSRS 是否擋)

Setup（一次）：
  pip install playwright
  playwright install chromium

用法：
  python scripts\\fetch_m7_report_playwright.py [--limit 5] [--reset|--resume] [--headed] [--workers N]

  --reset:   清 state + jsonl 重抓 (慎用,會 overwrite!)
  --resume:  從 jsonl 跳已有 EIDH (預設啟用 if jsonl 存在)
  --limit:   只抓前 N 個（測試）
  --headed:  顯示瀏覽器視窗（debug 用,預設 headless;workers > 1 時強制 headless）
  --workers: 並行 worker 數 (default 4, max 建議 8)
"""
import argparse
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
DESIGNS_JSONL = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
OUT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
STATE = DL / "data" / "ingest" / "metadata" / ".m7_report_state"

URL_TEMPLATE = "http://nt-net2/MTM/Report/M7FiveLevelReport.aspx?eidh={eidh}"

# 對應 HTML span id → 我們 schema key
FIELD_MAP = {
    "ResultCompany": "company",
    "ResultCustomer": "customer",
    "ResultFollow": "analyst_follow",
    "ResultStyleNo": "style_no",
    "ResultIndexNo": "index_no",
    "ResultItem": "item",
    "ResultFabric": "wk",                    # Woven/Knit
    "ResultFabricName": "fabric_name",       # Poplin
    "ResultContent": "fabric_ingredients",   # Recycled Polyester/Spandex 86/14
    "ResultType": "evaluation_type",
    "ResultOrigin1": "origin",
    "ResultQuantity": "quantity_dz",
    "ResultAnalystDate": "analyst_date",
    "ResultAnalystC": "analyst_creator",
    "ResultAnalystU": "analyst_update",
    "ResultReviewDate": "review_date",
    "ResultReviewer": "reviewer",
    "ResultReviewReason": "review_reason",
    "ResultHighLevel": "high_level_cost",
    "ResultFashion": "fashion_cost",
    "ResultPerformance": "performance_cost",
    "ResultNormal": "normal_cost",
    "ResultTotalDistribution": "total_amount_usd_dz",
    "ResultSewingTime": "sewing_time",
    "ResultSewingIE": "sewing_ie",
    "ResultCuttingTime": "cutting_time",
    "ResultCuttingIE": "cutting_ie",
    "ResultIroningTime": "ironing_time",
    "ResultIroningIE": "ironing_ie",
    "ResultPackageTime": "package_time",
    "ResultPackageIE": "package_ie",
    "ResultTotalTime": "total_time",
    "ResultTotalIE": "total_ie",
}

# Checkbox flags（image-based 或 ■/□）
FLAG_LABELS = ["Bonding", "Description", "Sample", "Complex Style",
               "Simple Style", "Thick Fabric", "Thin Fabric", "Align", "Non Align"]


def scrape_one(page, eidh, timeout_ms=15000):
    """開一個 EIDH 頁，等渲染完，抽 metadata"""
    url = URL_TEMPLATE.format(eidh=eidh)
    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    # 等真資料填入（ResultCustomer 不該還是 "Customer"）
    try:
        page.wait_for_function(
            "document.querySelector('#ResultCustomer')?.innerText !== 'Customer'",
            timeout=5000)
    except Exception:
        pass  # 即使沒等到也試抽看看

    out = {"eidh": eidh}
    # 抽 span 值
    for span_id, key in FIELD_MAP.items():
        try:
            el = page.query_selector(f'#{span_id}')
            if el:
                val = el.inner_text().strip()
                if val:
                    out[key] = val
        except Exception:
            pass

    # ════════ V2 解析：用 span ID 精準定位（avoid mega-table 全部混在一起）════════
    js = r"""() => {
        const out = {};

        // 1. IE / Time 數值（從 span 第一個 text node 取，避免 nested table）
        const ieMap = {
            'ResultTotalIE': 'total_ie',
            'ResultSewingIE': 'sewing_ie',
            'ResultCuttingIE': 'cutting_ie',
            'ResultIroningIE': 'ironing_ie',
            'ResultPackageIE': 'package_ie',
            'ResultCuttingTime': 'cutting_time',
            'ResultIroningTime': 'ironing_time',
            'ResultPackageTime': 'package_time',
        };
        for (const [id, key] of Object.entries(ieMap)) {
            const el = document.getElementById(id);
            if (el) {
                // 用第一個直接 text node，避免被 nested table 干擾
                let txt = '';
                for (const node of el.childNodes) {
                    if (node.nodeType === 3) { txt = (node.nodeValue || '').trim(); break; }
                }
                if (!txt) txt = (el.innerText || '').trim().split('\n')[0];
                out[key] = txt;
            }
        }

        // 2. Flags (img.src 含 'checked.jpg' 但不是 'unchecked.jpg')
        const flagMap = {
            'ResultBonding': 'bonding',
            'ResultComplexStyle': 'complex_style',
            'ResultNonAlign': 'non_align',
            'ResultAlign': 'align',
            'ResultDescription': 'description_present',
        };
        const flags = {};
        for (const [id, key] of Object.entries(flagMap)) {
            const img = document.getElementById(id);
            if (img && img.tagName === 'IMG') {
                const src = (img.src || '').toLowerCase();
                flags[key] = src.includes('checked.jpg') && !src.includes('unchecked.jpg');
            }
        }
        out.flags = flags;

        // 3. Machine tables — 用 span ID 內的 inner table
        const machineSections = {
            'ResultHighLevel': 'high_machines',
            'ResultNormal': 'custom_machines',
            'ResultFashion': 'fashion_machines',
            'ResultPerformance': 'performance_machines',
        };
        for (const [spanId, key] of Object.entries(machineSections)) {
            const span = document.getElementById(spanId);
            if (!span) { out[key] = []; continue; }
            const innerTbl = span.querySelector('table');
            if (!innerTbl) { out[key] = []; continue; }
            const rows = innerTbl.querySelectorAll('tr');
            const list = [];
            for (let i = 1; i < rows.length; i++) {  // skip th header
                const tds = rows[i].querySelectorAll('td');
                if (tds.length >= 5) {
                    list.push({
                        machine: tds[0].innerText.trim(),
                        auxiliary_tool: tds[1].innerText.trim(),
                        total_qty: tds[2].innerText.trim(),
                        apportionment_qty: tds[3].innerText.trim(),
                        apportionment_usd_dz: tds[4].innerText.trim(),
                    });
                }
            }
            out[key] = list;
        }

        // 4. Five-level summary — 從 #lblPartDetail 那行往後走，每 step 2 個 tr
        const partLabel = document.getElementById('lblPartDetail');
        const fiveLevel = [];
        if (partLabel) {
            // 找到 #lblPartDetail 所在的 tr，從下下個 tr 開始（跳過 header）
            let row = partLabel.closest('tr');
            if (row) row = row.nextElementSibling;  // 第一個是 col header
            // 跳過 col header (D0D0D0 bgcolor)
            while (row && (row.bgColor || '').toLowerCase() === '#d0d0d0') {
                row = row.nextElementSibling;
            }
            // 每個 step 由 2 個 tr 組成
            while (row) {
                const tds = row.querySelectorAll('td');
                if (tds.length >= 6) {
                    const tdArr = Array.from(tds);
                    // 找 Total_Second cell（display:none）
                    let totalSec = '';
                    let ieSec = '';
                    let methodDescribeAlt = '';
                    for (const td of tdArr) {
                        if (td.getAttribute('name') === 'Total_Second') {
                            totalSec = td.innerText.trim();
                        }
                    }
                    // 最後一個 td 是 IE 秒數
                    ieSec = tdArr[tdArr.length - 1].innerText.trim();
                    const category = tdArr[0].innerText.trim();
                    const part = tdArr[1].innerText.trim();
                    const shape = tdArr[2].innerText.trim();
                    const methodCode = tdArr[3].innerText.trim();
                    const methodDescribe = tdArr.length > 4 ? tdArr[4].innerText.trim() : '';
                    // row 2 = 第二個 tr（method_describe 第二行）
                    const row2 = row.nextElementSibling;
                    if (row2) {
                        const r2tds = row2.querySelectorAll('td');
                        if (r2tds.length === 1) {
                            methodDescribeAlt = r2tds[0].innerText.trim();
                        }
                    }
                    fiveLevel.push({
                        category, part,
                        shape_design: shape,
                        method_code: methodCode,
                        method_describe: methodDescribe,
                        method_describe_alt: methodDescribeAlt,
                        total_second: totalSec,
                        ie_seconds: ieSec,
                    });
                    row = row2 ? row2.nextElementSibling : null;
                } else {
                    row = row.nextElementSibling;
                }
            }
        }
        out.five_level_detail = fiveLevel;

        return out;
    }"""
    try:
        parsed = page.evaluate(js)
        # IE / Time 欄位（覆蓋舊抓的）
        for key in ("total_ie", "sewing_ie", "cutting_ie", "ironing_ie", "package_ie",
                    "cutting_time", "ironing_time", "package_time"):
            v = parsed.get(key)
            if v:
                out[key] = v
        if parsed.get("flags"):
            out["flags"] = parsed["flags"]
        for mk in ("high_machines", "custom_machines", "fashion_machines", "performance_machines"):
            if parsed.get(mk):
                out[mk] = parsed[mk]
        if parsed.get("five_level_detail"):
            out["five_level_detail"] = parsed["five_level_detail"]
    except Exception as e:
        print(f"  [!] {eidh}: parse fail: {e}", file=sys.stderr)

    return out


# === multiprocessing worker globals (each subprocess holds own Chrome) ===
_WORKER_PAGE = None  # set by _init_worker, used by _fetch_one


def _init_worker():
    """每個 worker process 啟動 Chrome 一次,後續 scrape 共用 page."""
    global _WORKER_PAGE
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    chrome_args = [
        "--auth-server-allowlist=nt-net2,*.nt-net2",
        "--auth-negotiate-delegate-allowlist=nt-net2,*.nt-net2",
        "--auth-schemes=basic,digest,ntlm,negotiate",
    ]
    try:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=chrome_args)
    except Exception:
        browser = pw.chromium.launch(headless=True, args=chrome_args)
    context = browser.new_context(ignore_https_errors=True)
    _WORKER_PAGE = context.new_page()


def _fetch_one(eidh):
    """單一 EIDH 抓取,在 worker process 內跑,共用 _WORKER_PAGE."""
    global _WORKER_PAGE
    try:
        data = scrape_one(_WORKER_PAGE, eidh)
        return ("ok", eidh, data)
    except Exception as e:
        return ("err", eidh, str(e))


def _load_done_eidhs(out_path):
    """讀 m7_report.jsonl 已有 EIDH set."""
    if not out_path.exists():
        return set()
    done = set()
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                e = d.get("eidh")
                if e is not None:
                    done.add(str(e))
            except Exception:
                continue
    return done


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--reset", action="store_true", help="清 state + jsonl 重抓 (慎用)")
    p.add_argument("--resume", action="store_true",
                   help="從 jsonl 跳已有 EIDH (預設 auto on if jsonl 存在 + not reset)")
    p.add_argument("--headed", action="store_true", help="顯示瀏覽器視窗 (workers=1 時才有效)")
    p.add_argument("--workers", type=int, default=4,
                   help="並行 worker 數 (default 4, max 建議 8)")
    p.add_argument("--max-seconds", type=int, default=3600)
    p.add_argument("--cdp-port", type=int, default=0,
                   help="CDP attach 到既有 Chrome (port 9222), 強制 workers=1")
    args = p.parse_args()
    # CDP / headed 不支援多 worker
    if args.cdp_port or args.headed:
        args.workers = 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] pip install playwright && playwright install chromium")
        sys.exit(1)

    if args.reset:
        if STATE.exists(): STATE.unlink()
        if OUT.exists(): OUT.unlink()
        print("[reset] state + jsonl cleared")

    # 讀 EIDH 共用 helper m7_eidh_loader.py
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_eidhs
    eidhs = [str(e) for e in load_eidhs()]
    if args.limit:
        eidhs = eidhs[:args.limit]

    # === Resume: 從 jsonl 跳已有 EIDH (預設啟用 if jsonl 存在 + not reset) ===
    done = set()
    auto_resume = (not args.reset) and OUT.exists()
    if args.resume or auto_resume:
        done = _load_done_eidhs(OUT)
        print(f"[resume] {len(done):,} EIDH already in jsonl, skipping")
    eidhs_todo = [e for e in eidhs if e not in done]
    if not eidhs_todo:
        print(f"═══ ALL DONE ═══ ({len(done)} already done, 0 to do)")
        return
    print(f"[plan] total {len(eidhs):,} EIDH, todo {len(eidhs_todo):,}, workers={args.workers}")

    t0 = time.time()
    n_ok = n_err = 0
    n_real = 0
    # 因 resume 後是 incremental append,permanently "a" mode
    open_mode = "a"

    # === Single-worker (legacy path, --headed / --cdp-port 才用) ===
    if args.workers <= 1:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if args.cdp_port:
                cdp_url = f"http://localhost:{args.cdp_port}"
                print(f"[browser] CDP attach to {cdp_url}")
                browser = pw.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0]
                page = context.new_page()
            else:
                chrome_args = [
                    "--auth-server-allowlist=nt-net2,*.nt-net2",
                    "--auth-negotiate-delegate-allowlist=nt-net2,*.nt-net2",
                    "--auth-schemes=basic,digest,ntlm,negotiate",
                ]
                try:
                    browser = pw.chromium.launch(channel="chrome",
                                                  headless=not args.headed,
                                                  args=chrome_args)
                except Exception:
                    browser = pw.chromium.launch(headless=not args.headed,
                                                  args=chrome_args)
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()

            with open(OUT, open_mode, encoding="utf-8") as fout:
                for i, eidh in enumerate(eidhs_todo):
                    if time.time() - t0 >= args.max_seconds:
                        print(f"  [!] hit {args.max_seconds}s budget at {i}, stopping")
                        break
                    try:
                        data = scrape_one(page, eidh)
                        if data.get("customer") and data["customer"] != "Customer":
                            n_real += 1
                        fout.write(json.dumps(data, ensure_ascii=False) + "\n")
                        fout.flush()
                        n_ok += 1
                        if i % 20 == 0:
                            print(f"  [{i}/{len(eidhs_todo)}] {eidh} → "
                                  f"{data.get('customer','?')} / {data.get('item','?')[:30]} "
                                  f"(ok={n_ok}, err={n_err}, real={n_real})")
                    except Exception as e:
                        print(f"  [!] {eidh}: {e}")
                        n_err += 1
            browser.close()
    else:
        # === Multi-worker (ProcessPoolExecutor, 每個 worker 自己 Chrome) ===
        print(f"[parallel] launching {args.workers} Chrome workers...")
        with open(OUT, open_mode, encoding="utf-8") as fout:
            with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker) as ex:
                futures = {ex.submit(_fetch_one, e): e for e in eidhs_todo}
                done_count = 0
                for fut in as_completed(futures):
                    if time.time() - t0 >= args.max_seconds:
                        print(f"  [!] hit {args.max_seconds}s budget at {done_count}, stopping")
                        # 殘餘 futures 會被 with-block 退出時 cancel
                        break
                    status, eidh, payload = fut.result()
                    if status == "ok":
                        if payload.get("customer") and payload["customer"] != "Customer":
                            n_real += 1
                        fout.write(json.dumps(payload, ensure_ascii=False) + "\n")
                        fout.flush()
                        n_ok += 1
                    else:
                        print(f"  [!] {eidh}: {payload}")
                        n_err += 1
                    done_count += 1
                    if done_count % 20 == 0:
                        rate = done_count / max(time.time() - t0, 0.1)
                        eta_min = (len(eidhs_todo) - done_count) / rate / 60
                        print(f"  [{done_count}/{len(eidhs_todo)}] "
                              f"(ok={n_ok}, err={n_err}, real={n_real}) "
                              f"rate={rate:.1f}/s ETA={eta_min:.0f}min")

    # 寫 state (累計已抓 = done + 本次抓的)
    final_done = len(done) + n_ok
    STATE.write_text(str(final_done))
    elapsed_min = (time.time() - t0) / 60
    print(f"\n[done] processed {n_ok + n_err} EIDHs in {elapsed_min:.1f} min "
          f"({n_ok} ok, {n_err} err, {n_real} 有真資料)")
    print(f"[state] cumulative {final_done}/{len(eidhs)} done")
    print(f"[output] {OUT}")
    if final_done >= len(eidhs):
        print(f"═══ ALL DONE ═══")


if __name__ == "__main__":
    main()
