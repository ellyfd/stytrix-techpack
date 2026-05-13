"""page_classifier.py — PDF page-level classifier for Techpack extraction.

每頁 PDF 分類成 4 類 (給 extract_pdf_all.py 的 page-level dispatch 用):
  - 'cover'        : metadata cover (Centric 8 / DSG / TGT 業務欄)
  - 'construction'      : construction callout page (做工標註, 給 VLM 餵料)
  - 'measurement'  : measurement chart / POM 表 (給 POM rules build)
  - 'junk'         : 其他 (POM tolerance / fit comments / reference / grade review ...)

抽自原 extract_raw_text_m7.py + extract_techpack.py + shared/pdf_helpers.py。
PullOn 多客戶版,對 21+ brand 通用。各 brand cover/mc 細節 layout 由 client_parsers/ 模組處理,
這裡只判斷 "page 屬於哪一類", 不做欄位抽取。
"""
from __future__ import annotations
import re
from typing import Optional


# ════════════════════════════════════════════════════════════
# Patterns / Keywords (抽自原 shared/pdf_helpers.py + extract_techpack.py)
# ════════════════════════════════════════════════════════════

# Callout / construction 判別
ISO_RE = re.compile(r"\b(301|401|406|503|504|512|514|515|516|601|602|605|607)\b")
MARGIN_RE = re.compile(r'\d+/\d+["”]')
NEEDLE_RE = re.compile(r"\b[23]N\b|\b[23]NDL\b|\b2N3TH\b|\b3N5TH\b", re.I)
SEW_KW = [
    "COVERSTITCH", "OVERLOCK", "TOPSTITCH", "FLATLOCK", "FLATSEAM",
    "BARTACK", "BAR TACK", "BLINDHEM", "BLIND HEM", "EDGESTITCH",
    "EDGE STITCH", "CHAINSTITCH", "CHAIN STITCH", "FELLED SEAM",
    "LAPPED SEAM", "SATIN STITCH", "CLEAN FINISH", "TURNBACK",
    "TURN BACK", "UNDERSTITCHED", "BINDING", "SERGE", "SERGED",
]
CONSTRUCTION_HEADER_KW = ["CONSTRUCTION CALLOUT", "INTERNAL/CONSTRUCTION"]
CONSTRUCTION_SOFT_KW = ["CALLOUT", "BOM REVIEW", "DESIGN BOM"]

# Junk 排除 (直接 skip 不抽)
EXCLUDE_TITLES = [
    "GRADE REVIEW", "REF IMAGES", "REFERENCE IMAGES",
    "INSPIRATION IMAGES", "INSPIRATION", "FIT COMMENTS",
    "FIT SAMPLE IMAGES", "PATTERN CORRECTIONS", "NEXT STEPS",
    "MOCK NECK REFERENCES",
]

# Measurement chart (POM 表) 判別
POM_HEADER_KW = ["POM NAME", "TOL FRACTION", "VENDOR ACTUAL", "SAMPLE EVAL", "QC EVALUATION"]
POM_ID_RE = re.compile(r"\b[A-Z]{1,3}\d{2,3}[A-Z]?\b")  # H2, K1.6, L2.6, N20 etc.
MC_STRUCTURE_KW = [
    "POM CODE", "POM NAME", "BASE SIZE", "BODY TYPE",
    "BRAND MC COMMENTS", "GRADE OF MEASUREMENTS",
    "MEASUREMENT CHART",
]

# Cover (Centric 8 / DSG / 一般 metadata cover) 判別
COVER_KW = [
    # Centric 8 (ONY/ATH/GAP/BR 集團)
    "DESIGN NUMBER", "DESIGN TYPE", "DESIGN SUB-TYPE", "BRAND/DIVISION",
    "BRAND DIVISION", "DEPARTMENT", "CARRY OVER", "REVISION", "FIT CAMP",
    "BOM PRIMARY", "SEASON PLANNING", "PRIMARY SUPPLIER", "BOM VERSION",
    "STATUS\tADOPTED", "DESIGN CONCEPT", "COSTING INFORMATION",
    # DKS (Dick's Sporting Goods — DSG/Calia/VRST), 2026-05-11 加
    "STYLE NUMBER", "STYLE DESCRIPTION", "PRODUCT STATUS", "SAMPLE STATUS",
    "TECH PACK TYPE", "PRODUCT ADDED TO LINE", "COMPONENT LAST MODIFIED",
    "SAMPLE OVERVIEW", "PRODUCT COLORWAY",
    # GU (UNIQLO subsidiary) — 日文 デザイン管理表, 2026-05-11 加
    "デザイン管理表", "デザイン名", "シーズン", "品番", "パーツ数",
    "作成者", "デザイナー",
    # KOH (Kohl's) — Tech Spec Overview, 2026-05-11 加
    "TECH SPEC OVERVIEW", "REQUEST NO.", "PRODUCT TYPE",
    # KOH Makalot Sample Room (聚陽打樣室出的 KOH spec sheet), 2026-05-12 加
    # 案例: 306171 / 306565 / 306890 / 307427 — 含 Style No + Customer KOHLS + Ref Style
    # 但 page 1 cover_kw_hits = 0 被誤分到 callout. KOH-specific markers:
    "REF STYLE",         # KOH Makalot 通用「參考樣式」欄位
    "TOSAMPLEROOM",      # KOH PDF 命名慣例 _ToSampleRoom_
    "DUMMY", "MISSY",    # Makalot Sample Room 的「樣衣假人」「Missy 號型」術語
    "STYLE NO",          # KOH Makalot 用 "Style No" (Centric 8 用 Design Number)
    # TGT (Target) — Product Attributes, 2026-05-11 加
    "PRODUCT ATTRIBUTES", "PRODUCT ID", "PRIMARY MATERIAL",
    "TARGET BRANDS", "TARGET CORPORATION",
    # TGT Makalot 內部 spec sheet for Target (All in Motion 線等), 2026-05-12 加
    # 案例: 306127/306125/306421/306422/306845 — 含 STYLE#:/AIM/Reference Style 但不命中 ≥3
    "STYLE#",            # Makalot 內部 spec sheet style 編號慣例 (STYLE#: AIMSS26W005)
    "ALL IN MOTION",     # Target's All in Motion (AIM 線) 子品牌
    "REFERENCE STYLE",   # Makalot Sample Room 「參考樣式」欄位
    # TGT 聚陽 Quotation 報價單 (Sample Making Request), 2026-05-12 加
    # 案例: 310137/310267/310179/310421/310872 — Stage:/Style:/Customer:/P'Cate:/MR: 表頭
    "P'CATE:",           # Product Category 縮寫 (極獨特, Quotation 報價單必有)
    "TARGET(TSS)",       # TGT TSS 子品牌 (Sample Sourcing Service)
    "TARGET(TSI)",       # TGT TSI 子品牌
    "ORDER QTY(DZ)",     # 報價單訂單欄
    "P'CATE",            # 短版 P'Cate 也可能命中
    # HLF (High Life) + ANF (A&F / Hollister) — Gerber Technology PLM, 2026-05-11 加
    "GERBER TECHNOLOGY", "COVER PAGE", "TECH PACK #",
    "STYLE TYPE APPAREL", "DIVISION HIGH LIFE",
    "BRAND GILLY HICKS", "BRAND HOLLISTER", "BRAND ABERCROMBIE",
    "STYLE CATEGORY", "SEASON YEAR",
    # ANF / Hollister 新版 PLM (A&F PROD), 2026-05-12 加
    # 案例: EIDH 312222 page 2 含完整 cover 但只命中 "DEPARTMENT" 1 個 → 誤判 junk
    # 只加 ANF-PLM 專屬 markers (避免跟 measurement chart 頁衝突):
    "A&F PROD",          # 強訊號 - ANF PLM server name
    "STYLE CODE",        # ANF 用 "Style Code", Centric 8 用 "Design Number"
    "DATA PACKAGE",      # ANF PLM 文件 type
    "UPDATED SPEC SHEET", # ANF PLM 常見 cover header
    # UA (Under Armour) — Cover Sheet Properties, 2026-05-11 加
    "COVER SHEET PROPERTIES", "UNDER ARMOUR", "SOURCING CLASS",
    "STYLE NAME", "FIT TYPE", "FABRICATION", "B&W SUB CATEGORY",
    "PRODUCT TEAM", "REGIONAL FIT",
    # BY (Beyond Yoga) — BILL OF MATERIALS, 2026-05-11 加
    "BILL OF MATERIALS", "BEYOND YOGA", "STYLE DESCRIPTION",
    "PRODUCT COLOR CODE", "DATE OF LAST CHANGE",
]

# BOM 表 (junk for our purposes — 既不是 callout 也不是 mc)
# 2026-05-12 擴張: BOM 文字會誤觸 8+ POM IDs heuristic, 需 early exclude
BOM_TABLE_KW = [
    # Centric 8 內部 BOM 系統 keyword
    "BOMCOLORMATRIX", "OWNER TYPE", "COMPONENTS\tDOCUMENTS",
    "BOM CC NUMBER", "PRODUCT SUSTAINABILITY",
    "BOM DETAILS", "MATERIAL NAME", "GAUGE/ENDS",
    "QUALITY DETAILS", "PRIMARY RD",
    "SUPPLIER ARTICLE", "CC NAME",
    "SUSTAINABILITY ATTRIBUTE",
    # 真實 BOM 頁的 strong indicators (2026-05-12 from BOM 誤判 audit)
    "BILL OF MATERIALS",      # ⚠ BY 客戶 cover 也用這詞, 要 client-aware
    "PRODUCT IMPRESSIONS", "BOM-",  # BOM-M5R83 等 BOM ID
    "ARTICLE #:", "ARTICLE#:", "ART-",
    "PIECE GOODS", "TRIM TYPE",
    "MAIN LABEL", "CARE LABEL", "HANGTAG",
    "MAIN HANGTAG", "POLY BAG",
    "FAS-", "FBR-", "TRM-",  # Centric 8 material code prefixes
    # WHITE FEATHER / TARARC 之類 color code, 太短不放
]


# ════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════

def classify_page(page, client_code: Optional[str] = None) -> tuple[str, dict]:
    """Classify a PyMuPDF page into one of 4 types.

    Args:
        page: PyMuPDF page object (fitz.Page)
        client_code: short brand code ('ONY', 'DKS', ...) — 給未來 client-specific 判斷預留

    Returns:
        (page_type, evidence_dict) where page_type in
        {'cover', 'construction', 'measurement', 'junk'} and evidence_dict has
        diagnostic info (score, n_images, n_drawings, reason, ...).
    """
    text = page.get_text()
    upper = text.upper()
    wc = len(text.split())
    evidence = {"word_count": wc, "reason": None}

    # === Step 1: 早期排除 junk ===
    for kw in EXCLUDE_TITLES:
        if kw in upper:
            evidence["reason"] = f"exclude_title:{kw}"
            return "junk", evidence

    # === Step 1.5: BOM 表早期排除 ===
    # BOM 內的 article number (OP101 / FAS-3L7YY) 會誤觸 8+ POM ID heuristic.
    # BOM 頁實際是 fabric/trim 描述, 對 MC 抽取無用 → junk.
    # 注意: BY 客戶 (Beyond Yoga) "BILL OF MATERIALS" 是 cover, 跳過此排除
    # 2026-05-12 修 v1: 若同時有 cover_kw ≥3 (e.g. Centric 8 "BOM Details" 頁含完整 metadata),
    #                  優先當 cover 用 — 否則整頁 metadata (design_number/season/design_type/fit_camp...) 會漏抽
    # 2026-05-12 修 v2: TGT AIM / KOH BTS 系列 spec sheet 含 STYLE# + fabric article (FAS-/FAB-),
    #                  cover_kw 可能 <3 但 STYLE# 是強訊號 → 也跳過 junk
    bom_signal_count = sum(1 for kw in BOM_TABLE_KW if kw in upper)
    is_by_brand = client_code == "BY"
    if bom_signal_count >= 2 and not is_by_brand:
        # 預檢 cover_kw — 若混合頁含完整 metadata, 不當 junk
        cover_kw_count = sum(1 for kw in COVER_KW if kw in upper)
        # 預檢 design code prefix — TGT AIM / KOH BTS / GAP D 系列 spec sheet
        # 這些 page 含 STYLE# 或 fabric article + 設計款號, 不應該當 BOM
        has_design_code = bool(re.search(
            r"\b(STYLE#|STYLE NO\.|"                          # 直接的 style 標記
            r"AIM[\w\-]{3,15}|SON[\w\-]{3,15}|TGT[\w\-]{3,15}|"           # TGT 線款號
            r"MST\d{2}[\w\-]{3,12}|"                              # TGT MSTAR 線
            r"C\d{3}MKCJ\w*|C\d{3}MK\w+|"                     # TGT C&J Cat & Jack 兒童線
            r"CBRTW\w{4,10}|BTS\d{2}\w{3,10}|"                # KOH 線款號
            r"D\d{4,6})\b",                                    # GAP/DKS D 系列款號
            text, re.IGNORECASE
        ))
        if cover_kw_count >= 3 or has_design_code:
            # 是 "BOM Details + cover metadata" 混合頁 (Centric 8 page 3 / TGT AIM / KOH BTS 典型),
            # fall through to Step 3 cover detection — 不要 early junk
            evidence["bom_signal_count"] = bom_signal_count
            evidence["cover_kw_count"] = cover_kw_count
            evidence["has_design_code"] = has_design_code
            # 不 return, 繼續走 Step 2/3
        elif not ("TOL (-)" in upper and "TOL (+)" in upper):
            # 雙重保險: 若同時有 TOL(-)/(+) (real MC) 才當 MC, 否則 BOM 直接 junk
            evidence["reason"] = f"bom_signal_x{bom_signal_count}"
            evidence["bom_kw_hits"] = [kw for kw in BOM_TABLE_KW if kw in upper][:5]
            return "junk", evidence

    # === Step 2: Measurement chart (POM 表) ===
    # 強訊號 1: "TOL (-)" + "TOL (+)" (Centric 8 POM 表標準格式)
    # 這是 MC 表的 unique signature, BOM 表不會有, 高可信度直接判 MC
    if "TOL (-)" in upper and "TOL (+)" in upper:
        evidence["reason"] = "tol_pos_neg"
        return "measurement", evidence

    # 強訊號 2: 8+ POM IDs PLUS 至少一個 confirming 信號
    # (BOM 內 OP101/FAS-3L7YY 之類 article number 會 false positive, 加 confirming 條件)
    pom_ids = POM_ID_RE.findall(text)
    if len(pom_ids) >= 8:
        # Confirming signals (real MC 頁特徵):
        #   - TOL keyword (any form)
        #   - "POM Name" / "POM Code" header
        #   - size column header (XS S M L XL 連續)
        #   - "Measurement Chart" 字面
        has_tol = "TOL" in upper and ("(-)" in upper or "(+)" in upper or "FRACTION" in upper)
        has_pom_header = "POM NAME" in upper or "POM CODE" in upper
        has_size_seq = bool(re.search(r"\bXS\s+S\s+M\s+L\b", upper) or
                            re.search(r"\bXXS\s+XS\b", upper))
        has_mc_title = "MEASUREMENT CHART" in upper
        if has_tol or has_pom_header or has_size_seq or has_mc_title:
            evidence["reason"] = f"{len(pom_ids)}_pom_ids+confirm"
            evidence["pom_ids_sample"] = pom_ids[:5]
            return "measurement", evidence
        # else: 沒 confirming → 可能是 BOM 誤判, fall through to other classification

    # 強訊號 3: "MEASUREMENT CHART" + 2+ mc structure 字 + 沒 callout 字
    if "MEASUREMENT CHART" in upper:
        mc_hits = sum(1 for kw in MC_STRUCTURE_KW if kw in upper)
        callout_hits = sum(1 for kw in CONSTRUCTION_HEADER_KW + CONSTRUCTION_SOFT_KW if kw in upper)
        if mc_hits >= 2 and callout_hits == 0:
            evidence["reason"] = f"mc_structure_x{mc_hits}"
            return "measurement", evidence

    # POM 表 helper keywords (POM NAME / TOL FRACTION) 強訊號
    if any(kw in upper for kw in POM_HEADER_KW):
        evidence["reason"] = "pom_header_kw"
        return "measurement", evidence

    # 強訊號 4: TGT PID layout (Centric 8 變體) — 用全字 "Point Of Measure" 跟
    # "+ Tolerance / - Tolerance" (而不是 POM NAME / TOL (-))
    # 2026-05-13 加: TGT 0% POM regression — 1340 件 PID PDF MC pages 都被誤分類成
    # construction (因為觸發不到 Step 2 強訊號 1-3 跟 POM_HEADER_KW)
    if "POINT OF MEASURE" in upper and ("+ TOLERANCE" in upper or "- TOLERANCE" in upper):
        evidence["reason"] = "tgt_pid_point_of_measure"
        return "measurement", evidence

    # 強訊號 5: BY Variance Report POM page (BY production 第二種 layout)
    # 2026-05-13 加: BY SD/LC/NN/PG/CR/PN 等 prefix 用「POM / PROTO / Description /
    # Reqstd Spec / Tol(+) / Tol(-) / Actual / Variance / POM Comments」layout,
    # POM code 是 B-HPS / B-WHF / B-WR 等 short dash format. text 偏少 (~1500 字元)
    # 觸發不到 8+ POM ID heuristic, 但 "POM" + "REQSTD" + "VARIANCE" combination unique.
    if "POM" in upper and "REQSTD" in upper and "VARIANCE" in upper:
        evidence["reason"] = "by_variance_report"
        return "measurement", evidence

    # 強訊號 6: CATO BidPackage POM page (Cato 單 sample size + 無 tolerance)
    # 2026-05-13 加: CATO 38 件 design 全 0% POM. PDF 是 Cato Corp BidPackage,
    # POM 表 layout: "Point of Measurement / Spec Cato" + T#### POM code + 單欄 M-size value
    if "POINT OF MEASUREMENT" in upper and "SPEC CATO" in upper:
        evidence["reason"] = "cato_bidpackage"
        return "measurement", evidence

    # 強訊號 7: Centric 8 Production(7.4) Measurement Chart Review layout
    # 2026-05-13 加: ONY/GAP/ATH/BR Production mode PLM export, 跟 Concept-en 完全不同 layout.
    # 不是 graded POM table (XXS-XXL), 而是 single-base-size + Target + Vendor Actual + HQ Actual 評估表.
    # 案例: EIDH 306119/306904 (D63709) / 314418 (D77485) / 315410 (D50698) / 325257 (D63456)
    # 觸發不到 Step 2 強訊號 1-3 (no "TOL (-)" 因為是 "Tol Fraction (-)") 也不到 POM_HEADER_KW.
    # Unique combination: "Centric 8 Production" + "Measurement Chart Review" 文字頭.
    if "MEASUREMENT CHART REVIEW" in upper and ("CENTRIC 8 PRODUCTION" in upper or "PRODUCTION(7.4)" in upper):
        evidence["reason"] = "centric8_production_mc_review"
        return "measurement", evidence

    # === Step 3: Cover (metadata cover, 通常前 2-3 頁) ===
    cover_hits = sum(1 for kw in COVER_KW if kw in upper)
    # 2026-05-12 加: 設計款號 prefix 是強訊號 (TGT AIM / KOH BTS / GAP D 系列 spec sheet)
    # 即使 cover_kw 只 2 個, 有 design code 仍當 cover
    has_design_code = bool(re.search(
        r"\b(STYLE#|STYLE NO\.|"                          # 直接的 style 標記
        r"AIM[\w\-]{3,15}|SON[\w\-]{3,15}|TGT[\w\-]{3,15}|"           # TGT 線款號
        r"MST\d{2}[\w\-]{3,12}|"                              # TGT MSTAR 線
        r"C\d{3}MKCJ\w*|C\d{3}MK\w+|"                     # TGT C&J Cat & Jack 兒童線
        r"CBRTW\w{4,10}|BTS\d{2}\w{3,10}|"                # KOH 線款號
        r"D\d{4,6})\b",                                    # GAP/DKS D 系列款號
        text, re.IGNORECASE
    ))
    if cover_hits >= 3:
        evidence["reason"] = f"cover_kw_x{cover_hits}"
        evidence["cover_kw_hits"] = cover_hits
        return "cover", evidence
    if cover_hits >= 1 and has_design_code:
        # 弱 cover signal + 強 design code = 接近 cover (TGT AIM spec sheet 典型)
        evidence["reason"] = f"cover_kw_x{cover_hits}+design_code"
        evidence["cover_kw_hits"] = cover_hits
        evidence["has_design_code"] = True
        return "cover", evidence

    # === Step 4: BOM 表 (junk for our purposes) ===
    bom_hits = sum(1 for kw in BOM_TABLE_KW if kw in upper)
    if bom_hits >= 1:
        # 同樣: 有 design code 不當 BOM, 給 callout/construction 評分機會
        if has_design_code:
            evidence["bom_hits_skipped"] = bom_hits
            # fall through to Step 5
        else:
            evidence["reason"] = f"bom_table_x{bom_hits}"
            return "junk", evidence

    # === Step 5: Callout / construction (評分制 score >= 5) ===
    try:
        n_images = len(page.get_images(full=True))
    except Exception:
        n_images = 0
    try:
        n_drawings = len(page.get_drawings())
    except Exception:
        n_drawings = 0

    score = 0
    breakdown = []

    if ISO_RE.search(text):
        score += 3
        breakdown.append("iso+3")
    if any(k in upper for k in CONSTRUCTION_HEADER_KW):
        score += 3
        breakdown.append("header+3")
    if any(k in upper for k in CONSTRUCTION_SOFT_KW):
        score += 2
        breakdown.append("soft+2")
    if any(k in upper for k in SEW_KW):
        score += 2
        breakdown.append("sew+2")
    if MARGIN_RE.search(text):
        score += 2
        breakdown.append("margin+2")
    if NEEDLE_RE.search(text):
        score += 1
        breakdown.append("needle+1")
    if n_images >= 1 or n_drawings >= 10:
        score += 3
        breakdown.append(f"img+3(img={n_images},draw={n_drawings})")
    if n_drawings >= 30:
        score += 2
        breakdown.append("draw30+2")
    if "ADDITIONAL COMMENTS" in upper:
        score -= 3
        breakdown.append("addtl_comments-3")
    if "BOM" in upper and "CATEGORY" in upper:
        score -= 2
        breakdown.append("bom_cat-2")

    # 圖密集 + 字少 callout 頁強制過關
    if any(k in upper for k in CONSTRUCTION_SOFT_KW) and n_images >= 1 and wc < 200:
        score = max(score, 5)
        breakdown.append("force5_image_callout")

    evidence["score"] = score
    evidence["score_breakdown"] = breakdown
    evidence["n_images"] = n_images
    evidence["n_drawings"] = n_drawings

    if score >= 5:
        evidence["reason"] = f"construction_score{score}"
        return "construction", evidence

    evidence["reason"] = f"low_score{score}"
    return "junk", evidence


def classify_pdf(pdf_path) -> list[dict]:
    """跑全 PDF 每頁 classify, 回傳 list of {page, type, evidence}.

    Args:
        pdf_path: PDF file path

    Returns:
        list of {page: int (1-indexed), type: str, evidence: dict}
    """
    try:
        import fitz
    except ImportError:
        return []

    out = []
    try:
        doc = fitz.open(str(pdf_path))
        for i in range(doc.page_count):
            page = doc[i]
            ptype, evidence = classify_page(page)
            out.append({
                "page": i + 1,
                "type": ptype,
                "evidence": evidence,
            })
        doc.close()
    except Exception as e:
        import sys
        print(f"  [!] classify_pdf fail {pdf_path}: {e}", file=sys.stderr)
    return out
