"""
Rebuild v4.3 ISO lookup — FUZZY matching for garbled Centric 8 callout text.
Key insight: pdfplumber strips spaces from Construction Callout pages.
Strategy: collapse text, do substring matching, allow OCR substitutions (O↔0).
"""
import os, re, json
from collections import defaultdict, Counter

BASE = "/sessions/upbeat-cool-hawking/mnt/Source-Data/ONY"
EXTRACT_DIR = f"{BASE}/_parsed/construction_extracts"
CLASS_FILE = f"{BASE}/pom_analysis_v5.5.1/data/all_designs_gt_it_classification.json"
OUT_FILE = f"{BASE}/v4.3_update_20260420/iso_lookup_factory_v4.3.json"
OUT_COPY = f"{BASE}/General Model_Path2_Construction Suggestion/iso_lookup_factory_v4.3.json"

# ── L1 keyword patterns for COLLAPSED text (no spaces) ──
# These match substrings after removing all spaces and uppercasing
L1_COLLAPSED = {
    'WB': ['WAISTBAND', 'WAIST', 'ELASTICWB', 'WBSEAM', 'WBENCASED', 'W/B', 'WB'],
    'NK': ['NECKLINE', 'NECKBAND', 'NECKTOP', 'NECKTAPE', 'NECKBIND', 'VNECK', 
           'CREWNECK', 'FUNNELNECK', 'BACKNECK', 'FRONTNECK', 'CBNECK', 'CFNECK',
           'COLLAR', 'NECK'],
    'NT': ['NECKTAPE', 'NECKBINDING', 'NECKTRIM', 'BINDINGATNECK', 'BINDINGAT NECK'],
    'PK': ['POCKET', 'PKT', 'POCKETBAG', 'SIDEPOCKET', 'HANDPOCKET', 'CARGOPOCKET',
           'BACKPOCKET', 'FRONTPOCKET', 'WELTPOCKET'],
    'SL': ['SLEEVE(?!CUFF|HEM|OPEN|VENT)', 'SLEEVESET', 'SLEEVESEAM'],
    'SB': ['SLEEVECUFF', 'SLEEVEOPENING', 'SLEEVEHEM', 'SELFCUFF', 'RIBCUFF', 'CUFFSEAM',
           'CUFFEDGE'],
    'HD': ['HOOD', 'HOODIE', 'HOODED'],
    'PL': ['PLACKET', 'FRONTPLACKET', 'HALFZIP', '1/2ZIP', 'FULLZIP'],
    'SR': ['SIDESEAM', 'SIDESEAMS', 'SS:'],
    'BS': ['BARTACK', 'TACK'],
    'BM': ['BOTTOMHEM', 'BOTTOMOPENING', 'BOTTOMEDGE', 'LEGOPENING', 'LEGHEM',
           'LEGEDGE', 'HEM(?!.*SLEEVE|.*CUFF)'],
    'ST': ['TOPSTITCH', 'STRADDLESTITCH', 'COVERSTITCH', 'CHAINSTITCH', 'STITCH'],
    'FY': ['FRONTFLY', 'FLYFRONT', 'FRONTBODY', 'FRONTPANEL'],
    'BN': ['BACKBODY', 'BACKPANEL', 'BACKYOKE'],
    'AH': ['ARMHOLE', 'ARMHOLESEAM'],
    'SH': ['SHOULDER', 'SHOULDERSEAM'],
    'DC': ['DECORAT'],
    'LB': ['LABEL', 'LOGO', 'CARELABEL'],
    'LI': ['LINING', 'INTERIORBRA'],
    'ZP': ['ZIPPER', 'ZIPPERGUARD', 'FLYZIP', 'ZIPPERTAPE'],
    'SA': ['SEAMALLOW'],
    'PS': ['OUTSEAM', 'INSEAM', 'RISE'],
    'RS': ['CROTCH', 'GUSSET', 'FRTRISE', 'BKRISE', 'FRONTRISE', 'BACKRISE', 'RISE'],
    'LO': ['ELASTIC', 'DRAWCORD', 'DRAWSTRING', 'BUNGEE', 'ENCASEDELASTIC',
           'RUBBERELASTIC'],
    'PD': ['PATCH'],
    'TH': ['THUMBHOLE'],
    'HL': ['BUTTONHOLE', 'EYELET', 'GROMMET'],
    'QT': ['QUILT'],
    'FP': ['FLAP', 'FLAPEDGE'],
    'SP': ['SLEEVEVENT', 'SLEEVEPLACK'],
    'LP': ['BELTLOOP', 'LOOP'],
    'NP': ['NECKPLACKET'],
    'BP': ['BODYPANEL'],
    'DP': ['DECORATIVEPANEL'],
    'AE': ['DECORATIVEEDGE'],
    'KH': ['KEYHOLE'],
    'OT': [],
    'SS': ['SIDEPANEL'],
}

# Compile L1 patterns for collapsed text
L1_COMPILED_COLLAPSED = {}
for code, keywords in L1_COLLAPSED.items():
    if keywords:
        pats = [kw.replace(' ', '') for kw in keywords]
        L1_COMPILED_COLLAPSED[code] = re.compile('|'.join(pats), re.IGNORECASE)

# Also keep NORMAL-text patterns for clean text (PPTX etc)
L1_NORMAL = {
    'WB': [r'腰頭', r'腰帶', r'腰部', r'WAISTBAND', r'WAIST\b'],
    'NK': [r'領[^襟貼]', r'領口', r'領圈', r'圓領', r'V領', r'NECK(?!.*TAPE|.*PLACK)', r'COLLAR', r'NECKLINE'],
    'NT': [r'領口貼', r'NECK\s*TAPE', r'NECK\s*BIND'],
    'PK': [r'口袋', r'袋口', r'袋布', r'袋身', r'POCKET'],
    'SL': [r'袖[^叉口]', r'袖子', r'SLEEVE(?!.*OPEN|.*CUFF|.*HEM|.*VENT)'],
    'SB': [r'袖口', r'SLEEVE\s*CUFF', r'SLEEVE\s*HEM', r'CUFF'],
    'HD': [r'帽[^釦]', r'帽子', r'HOOD'],
    'PL': [r'門襟', r'PLACKET'],
    'SR': [r'脅邊', r'側骨', r'SIDE\s*SEAM'],
    'BS': [r'車止', r'BARTACK'],
    'BM': [r'下襬', r'下擺', r'褲腳', r'擺口', r'LEG\s*OPEN', r'LEG\s*HEM', r'BOTTOM\s*HEM', r'BOTTOM\s*OPEN'],
    'ST': [r'車線', r'車縫', r'TOPSTITCH', r'COVERSTITCH', r'CHAINSTITCH'],
    'FY': [r'前幅', r'前身', r'FRONT\s*FLY'],
    'BN': [r'後幅', r'後身', r'BACK\s*PANEL', r'BACK\s*YOKE'],
    'AH': [r'袖窿', r'袖籠', r'ARMHOLE'],
    'SH': [r'肩[^縫章帶]', r'肩線', r'SHOULDER'],
    'DC': [r'裝飾', r'DECORAT'],
    'LB': [r'標[^準]', r'嘜頭', r'LABEL', r'CARE\s*LABEL'],
    'LI': [r'裡布', r'裡襯', r'LINING'],
    'ZP': [r'拉鏈', r'拉鍊', r'ZIPPER', r'ZIP(?!PER)'],
    'SA': [r'縫份', r'SEAM\s*ALLOW'],
    'PS': [r'褲合身', r'外長', r'OUTSEAM'],
    'RS': [r'起翹', r'褲襠', r'前檔', r'後檔', r'RISE', r'CROTCH', r'GUSSET'],
    'LO': [r'鬆緊', r'ELASTIC', r'DRAWSTRING', r'DRAWCORD'],
    'PD': [r'貼片', r'PATCH'],
    'TH': [r'腰繩', r'THUMBHOLE'],
    'HL': [r'釦環', r'BUTTONHOLE'],
    'QT': [r'行縫', r'QUILT'],
    'FP': [r'袋蓋', r'FLAP'],
    'SP': [r'袖叉', r'SLEEVE\s*VENT'],
    'LP': [r'帶絆', r'BELT\s*LOOP'],
    'SS': [r'SIDE\s*PANEL'],
    'NP': [r'領片', r'NECK\s*PIECE'],
    'BP': [r'腰褲', r'BODY\s*PANEL'],
    'DP': [r'裝飾片'],
    'AE': [r'裝飾邊'],
    'KH': [r'鈕眼', r'KEY\s*HOLE'],
    'OT': [],
}

L1_COMPILED_NORMAL = {}
for code, pats in L1_NORMAL.items():
    if pats:
        L1_COMPILED_NORMAL[code] = re.compile('|'.join(pats), re.IGNORECASE)

# ISO pattern — also handle OCR errors: O→0, l→1
# "4O1" = 401, "5O1" = 501, etc.
ISO_STRICT = re.compile(r'\b(301|304|401|406|407|501|503|504|514|515|516|602|605|607)\b')
ISO_FUZZY = re.compile(r'(?:^|[^0-9])(3[O0][14]|4[O0][167]|5[O0][1345]|51[456]|6[O0][257])[^0-9]', re.IGNORECASE)

def normalize_iso(s):
    """Normalize OCR-garbled ISO: replace O→0, l→1"""
    return s.upper().replace('O', '0').replace('l', '1').replace('I', '1')

def extract_iso_from_text(text):
    """Extract ISO codes from text, handling both clean and garbled."""
    isos = set()
    # Strict first
    for m in ISO_STRICT.finditer(text):
        isos.add(m.group(1))
    # Fuzzy for garbled text
    for m in ISO_FUZZY.finditer(text):
        normalized = normalize_iso(m.group(1))
        if normalized in {'301','304','401','406','407','501','503','504','514','515','516','602','605','607'}:
            isos.add(normalized)
    return isos

# L1 38-code reference
L1_38 = {
    'AE': {'zh': '裝飾邊', 'en': 'Decorative Edge'},
    'AH': {'zh': '袖窿', 'en': 'Armhole'},
    'BM': {'zh': '下襬', 'en': 'Bottom Hem'},
    'BN': {'zh': '後幅', 'en': 'Back Panel'},
    'BP': {'zh': '腰褲', 'en': 'Body Panel'},
    'BS': {'zh': '車止', 'en': 'Bar tack / Stitch Stop'},
    'DC': {'zh': '裝飾車', 'en': 'Decorative Stitch'},
    'DP': {'zh': '裝飾片', 'en': 'Decorative Panel'},
    'FP': {'zh': '袋蓋', 'en': 'Flap'},
    'FY': {'zh': '前幅', 'en': 'Front Yoke'},
    'HD': {'zh': '帽', 'en': 'Hood'},
    'HL': {'zh': '釦環', 'en': 'Buttonhole'},
    'KH': {'zh': '鈕眼', 'en': 'Key Hole'},
    'LB': {'zh': '標', 'en': 'Label'},
    'LI': {'zh': '裡布', 'en': 'Lining'},
    'LO': {'zh': '鬆緊帶', 'en': 'Elastic / Drawstring'},
    'LP': {'zh': '帶絆', 'en': 'Loop'},
    'NK': {'zh': '領', 'en': 'Neckline / Collar'},
    'NP': {'zh': '領片', 'en': 'Neck Piece'},
    'NT': {'zh': '領口貼邊', 'en': 'Neck Tape / Binding'},
    'OT': {'zh': '其它', 'en': 'Other'},
    'PD': {'zh': '貼片', 'en': 'Patch'},
    'PK': {'zh': '口袋', 'en': 'Pocket'},
    'PL': {'zh': '門襟', 'en': 'Placket'},
    'PS': {'zh': '壓線', 'en': 'Pressing Line'},
    'QT': {'zh': '行縫固定棉', 'en': 'Quilting'},
    'RS': {'zh': '起翹', 'en': 'Rise'},
    'SA': {'zh': '縫份', 'en': 'Seam Allowance'},
    'SB': {'zh': '袖口', 'en': 'Sleeve Cuff'},
    'SH': {'zh': '肩', 'en': 'Shoulder'},
    'SL': {'zh': '袖', 'en': 'Sleeve'},
    'SP': {'zh': '袖叉', 'en': 'Sleeve Vent'},
    'SR': {'zh': '脅邊', 'en': 'Side Seam'},
    'SS': {'zh': '脅邊', 'en': 'Side Panel'},
    'ST': {'zh': '車線', 'en': 'Stitch Line'},
    'TH': {'zh': '腰繩', 'en': 'Thread / Drawstring'},
    'WB': {'zh': '腰頭', 'en': 'Waistband'},
    'ZP': {'zh': '拉鏈', 'en': 'Zipper'},
}

GT_ALIAS = {
    '3RD_PIECE': 'OUTERWEAR', 'BODYSUIT_ONESIE': 'BODYSUIT',
    'JOGGER': 'JOGGERS', 'TOPS': 'TOP', 'PANT': 'PANTS',
}

GENDER_NORMALIZE = {
    'WOMENS': 'WOMENS', 'MENS': 'MENS', 'GIRLS': 'GIRLS', 'BOYS': 'BOYS',
    'BABY/TODDLER': 'BABY/TODDLER', 'MATERNITY': 'MATERNITY',
    'UNKNOWN': 'UNISEX', '': 'UNISEX',
}

WINDOW_SIZE = 4

def extract_design_id_from_name(filename):
    m = re.search(r'(D\d{4,6})', filename)
    return m.group(1) if m else None

def extract_design_id_from_content(filepath, max_lines=10):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f):
                if i >= max_lines: break
                m = re.search(r'(D\d{4,6})', line)
                if m: return m.group(1)
    except: pass
    return None

def is_callout_page(lines, start_idx, end_idx):
    """Check if a page section looks like a Construction Callout page."""
    section = ' '.join(lines[start_idx:end_idx])
    return bool(re.search(r'CONSTRUCTION\s*CALLOUT|DesignBoMReview|DesignBOM|CALLOUT', section, re.IGNORECASE))

def scan_file_fuzzy(filepath):
    """
    Scan a .txt file with TWO strategies:
    1. NORMAL matching: for clean text (PPTX, some PDFs) — window-based, same as v3
    2. FUZZY matching: for garbled text (Centric 8 callout pages) — collapse spaces, substring match
    """
    result = defaultdict(Counter)
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except:
        return result
    
    lines = text.split('\n')
    
    # === Strategy 1: NORMAL window-based matching (for clean text) ===
    for i, line in enumerate(lines):
        line_strip = line.strip()
        if not line_strip or line_strip.startswith('---'):
            continue
        
        isos = extract_iso_from_text(line_strip)
        if not isos:
            continue
        
        # Window: current + prev 4 lines
        window_start = max(0, i - WINDOW_SIZE)
        window_text = ' '.join(l.strip() for l in lines[window_start:i+1] 
                              if l.strip() and not l.strip().startswith('---'))
        
        for code, pat in L1_COMPILED_NORMAL.items():
            if pat.search(window_text):
                for iso in isos:
                    result[code][iso] += 1
    
    # === Strategy 2: FUZZY collapsed matching (for garbled callout text) ===
    # Split text into page sections
    page_sections = []
    current_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('--- p'):
            if current_start < i:
                page_sections.append((current_start, i))
            current_start = i
    if current_start < len(lines):
        page_sections.append((current_start, len(lines)))
    
    for start, end in page_sections:
        section_lines = lines[start:end]
        section_text = '\n'.join(section_lines)
        
        # Skip if this doesn't look like a callout page
        if not re.search(r'CALLOUT|callout|Callout|BoMReview|BOMReview|CONSTRUCTION', 
                        section_text.replace(' ', '')):
            # Also try: does it have garbled zone keywords?
            collapsed = section_text.upper().replace(' ', '')
            if not re.search(r'WAISTBAND|POCKET|SIDESEAM|ARMHOLE|SLEEVE|NECKLINE|'
                           r'HEMFINISH|BOTTOMHEM|LEGOPENING|ZIPPER|ELASTIC|HOOD|'
                           r'COVERSTITCH|CHAINSTITCH|TOPSTITCH|OVERLOCK|FLATLOCK',
                           collapsed):
                continue
        
        # Process each line in the callout section with COLLAPSED matching
        for i, line in enumerate(section_lines):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('---'):
                continue
            
            # Collapse the line
            collapsed_line = line_stripped.upper().replace(' ', '')
            
            # Find ISO in collapsed line (handles "4O1", "5O1" etc)
            isos = extract_iso_from_text(collapsed_line)
            
            if isos:
                # Look for zones in WINDOW of collapsed lines
                w_start = max(0, i - WINDOW_SIZE)
                window_collapsed = ''.join(
                    sl.strip().upper().replace(' ', '') 
                    for sl in section_lines[w_start:i+1]
                    if sl.strip() and not sl.strip().startswith('---')
                )
                
                for code, pat in L1_COMPILED_COLLAPSED.items():
                    if pat.search(window_collapsed):
                        for iso in isos:
                            result[code][iso] += 1
            
            # ALSO: check if this line has zone keyword even without ISO on same line
            # Then look for ISO in NEXT few lines
            else:
                collapsed_line_check = collapsed_line
                matched_zones_here = []
                for code, pat in L1_COMPILED_COLLAPSED.items():
                    if pat.search(collapsed_line_check):
                        matched_zones_here.append(code)
                
                if matched_zones_here:
                    # Look ahead for ISO
                    for j in range(i+1, min(i+1+WINDOW_SIZE, len(section_lines))):
                        ahead_line = section_lines[j].strip().upper().replace(' ', '')
                        ahead_isos = extract_iso_from_text(ahead_line)
                        if ahead_isos:
                            for code in matched_zones_here:
                                for iso in ahead_isos:
                                    result[code][iso] += 1
                            break  # Only match to nearest ISO
    
    # === Strategy 3: "All body seams are XXX" default rule ===
    # This sets the DEFAULT ISO for all unspecified zones
    default_iso_match = re.search(
        r'[Aa]ll\s*(?:body\s*)?seams?\s*(?:are|is)\s*(\d{3})(?:\s*[+&]\s*(\d{3}))?',
        text.replace(' ', ' ')  # keep some spaces for this pattern
    )
    if not default_iso_match:
        # Try collapsed version
        collapsed_all = text.upper().replace(' ', '')
        dm = re.search(r'ALLBODYSEAMSARE(\d{3})', collapsed_all)
        if dm:
            default_iso_match = dm
    
    if default_iso_match:
        default_iso = normalize_iso(default_iso_match.group(1))
        if default_iso in {'301','304','401','406','407','501','503','504','514','515','516','602','605','607'}:
            # Apply to common zones that don't have explicit ISO yet
            for code in ['SR', 'SH', 'AH', 'PS', 'RS']:
                if code not in result:
                    result[code][default_iso] += 1
    
    return result

def main():
    print("Step 1: Loading GT/IT classification...")
    with open(CLASS_FILE) as f:
        classifications = json.load(f)
    print(f"  {len(classifications)} designs")
    
    print("\nStep 2: Collecting files...")
    all_files = []
    need_content_lookup = []

    # PDF extracts
    pdf_dir = f"{EXTRACT_DIR}/pdf"
    for root, dirs, files in os.walk(pdf_dir):
        for fname in files:
            if fname.endswith('.txt'):
                fpath = os.path.join(root, fname)
                did = extract_design_id_from_name(fname)
                if did:
                    all_files.append((fpath, did))
                else:
                    need_content_lookup.append(fpath)

    # PPTX extracts
    pptx_dir = f"{EXTRACT_DIR}/pptx"
    if os.path.isdir(pptx_dir):
        for fname in os.listdir(pptx_dir):
            if fname.endswith('.txt'):
                fpath = os.path.join(pptx_dir, fname)
                did = extract_design_id_from_name(fname)
                if did:
                    all_files.append((fpath, did))
                else:
                    need_content_lookup.append(fpath)

    # Bucket extracts
    bucket_dir = f"{BASE}/_parsed/construction_by_bucket"
    if os.path.isdir(bucket_dir):
        for bucket in os.listdir(bucket_dir):
            txt_dir = os.path.join(bucket_dir, bucket, 'txt')
            if not os.path.isdir(txt_dir): continue
            for fname in os.listdir(txt_dir):
                if fname.endswith('.txt'):
                    fpath = os.path.join(txt_dir, fname)
                    did = fname.replace('.txt', '')
                    all_files.append((fpath, did))

    print(f"  {len(all_files)} files with D-number in filename")
    print(f"  {len(need_content_lookup)} need content lookup...")

    content_found = 0
    for fpath in need_content_lookup:
        did = extract_design_id_from_content(fpath)
        if did:
            all_files.append((fpath, did))
            content_found += 1
    print(f"  {content_found} resolved from content")
    print(f"  Total: {len(all_files)} files")
    
    print("\nStep 3: Scanning with fuzzy matching...")
    design_zones = defaultdict(lambda: defaultdict(Counter))
    
    for idx, (filepath, did) in enumerate(all_files):
        if idx % 2000 == 0 and idx > 0:
            print(f"  ...{idx}/{len(all_files)} files scanned")
        zones = scan_file_fuzzy(filepath)
        for l1, iso_counts in zones.items():
            for iso, cnt in iso_counts.items():
                design_zones[did][l1][iso] += cnt
    
    designs_with_data = {d for d, zones in design_zones.items() if zones}
    print(f"  {len(designs_with_data)} designs with zone-ISO data")
    
    # Debug: count how many from each source
    pdf_designs = set()
    pptx_designs = set()
    bucket_designs = set()
    for fpath, did in all_files:
        if did not in designs_with_data:
            continue
        if '/pptx/' in fpath:
            pptx_designs.add(did)
        elif '/construction_by_bucket/' in fpath:
            bucket_designs.add(did)
        else:
            pdf_designs.add(did)
    print(f"    From PDF: {len(pdf_designs)}, PPTX: {len(pptx_designs)}, Bucket: {len(bucket_designs)}")
    
    print("\nStep 4: Joining metadata + aggregating...")
    group_data = defaultdict(Counter)
    group_designs = defaultdict(set)
    
    unmatched = 0
    for did, zones in design_zones.items():
        if not zones: continue
        
        cls = classifications.get(did, {})
        gt = cls.get('gt', 'UNKNOWN')
        gt = GT_ALIAS.get(gt, gt)
        gender_raw = cls.get('gender', 'UNKNOWN')
        gender = GENDER_NORMALIZE.get(gender_raw, gender_raw)
        
        dept_raw = cls.get('dept', '') or cls.get('department_raw', '')
        d_upper = dept_raw.upper() if dept_raw else ''
        if 'SWIM' in d_upper:
            department = 'Swimwear'
        elif 'SLEEP' in d_upper or 'LOUNGE' in d_upper:
            department = 'Sleepwear'
        else:
            department = 'General'
        
        if not cls: unmatched += 1
        
        for l1, iso_counts in zones.items():
            if l1 not in L1_38: continue
            key = (department, gender, gt, l1)
            for iso, cnt in iso_counts.items():
                group_data[key][iso] += cnt
            group_designs[key].add(did)
    
    if unmatched:
        print(f"  ⚠️ {unmatched} designs not in classification table")
    
    # Build entries
    entries = []
    for (dept, gender, gt, l1), iso_counts in sorted(group_data.items()):
        total = sum(iso_counts.values())
        dist = {iso: round(cnt / total, 3) for iso, cnt in sorted(iso_counts.items(), key=lambda x: -x[1])}
        top_iso = max(dist, key=dist.get)
        top_pct = dist[top_iso]
        n_designs = len(group_designs[(dept, gender, gt, l1)])
        
        if n_designs >= 5 and top_pct >= 0.6:
            conf = 'strong'
        elif n_designs >= 3 and top_pct >= 0.4:
            conf = 'likely'
        elif n_designs >= 3:
            conf = 'mixed'
        else:
            conf = 'no_data'
        
        entries.append({
            'department': dept,
            'gender': gender,
            'gt': gt,
            'l1_code': l1,
            'l1': L1_38[l1]['zh'],
            'iso': top_iso,
            'iso_pct': top_pct,
            'confidence': conf,
            'n_designs': n_designs,
            'iso_distribution': dist,
        })
    
    output = {
        'version': '4.3',
        'rebuild_date': '2026-04-21',
        'description': 'ISO lookup by Department×Gender×GT×L1(38碼) — fuzzy matching for garbled Centric 8 text',
        'method': 'dual-strategy: normal window-based + fuzzy collapsed substring matching + "all seams are X" default rule',
        'sources': {
            'pdf_extracts': f'9,557 files',
            'pptx_extracts': f'6,998 files',
            'bucket_extracts': f'637 files',
        },
        'l1_standard_38': L1_38,
        'stats': {
            'total_entries': len(entries),
            'unique_designs': len(designs_with_data),
            'total_files_scanned': len(all_files),
            'l1_codes_with_data': sorted(set(e['l1_code'] for e in entries)),
            'l1_codes_no_data': sorted(set(L1_38.keys()) - set(e['l1_code'] for e in entries)),
            'confidence_breakdown': dict(Counter(e['confidence'] for e in entries)),
            'gt_values': sorted(set(e['gt'] for e in entries)),
            'gender_values': sorted(set(e['gender'] for e in entries)),
        },
        'entries': entries,
    }
    
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    os.makedirs(os.path.dirname(OUT_COPY), exist_ok=True)
    with open(OUT_COPY, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*50}")
    print(f"v4.3 FUZZY Rebuild Complete")
    print(f"{'='*50}")
    print(f"Entries:    {len(entries)}")
    print(f"Designs:    {len(designs_with_data)}")
    print(f"Files:      {len(all_files)}")
    print(f"L1 codes:   {len(output['stats']['l1_codes_with_data'])}/38")
    print(f"L1 no data: {output['stats']['l1_codes_no_data']}")
    print(f"Confidence: {output['stats']['confidence_breakdown']}")
    print(f"GT:         {output['stats']['gt_values']}")
    print(f"Gender:     {output['stats']['gender_values']}")
    print(f"\nWritten to: {OUT_FILE}")
    print(f"Copied to:  {OUT_COPY}")

if __name__ == '__main__':
    main()
