"""
VLM-based Construction Callout Extraction Pipeline
===================================================
Replaces pdfplumber text-based extraction for Centric 8 Construction Callout pages.

Key insight: Callout annotations are in the PDF GRAPHIC layer, not text layer.
pdfplumber/fitz extract 0 zone keywords from callout pages.
VLM (vision language model) reads the rendered image directly.

Pipeline: PDF → detect callout pages → render images → VLM extract → Glossary → ISO

Usage (PoC mode - Claude reads images manually):
    python vlm_pipeline.py --detect-only   # Step 1: find callout pages, render images
    # Then Claude reads images and fills vlm_raw_extracts.json
    python vlm_pipeline.py --map-iso       # Step 2: apply Glossary mapping

Usage (future API mode):
    python vlm_pipeline.py --api-key=xxx   # Full auto with Claude Vision API
"""

import os, re, json, sys
from collections import defaultdict

# ============================================================
# CONFIG
# ============================================================
BASE = "/sessions/upbeat-cool-hawking/mnt/Source-Data/ONY"
OUT_DIR = "/sessions/upbeat-cool-hawking/vlm_poc"
CLASS_FILE = f"{BASE}/pom_analysis_v5.5.1/data/all_designs_gt_it_classification.json"

# ============================================================
# PART 1: GAP/ONY GLOSSARY → ISO MAPPING
# ============================================================

# ONY-specific terminology (from glossary-customer-rules.md § ONY)
# Plus generic GAP Inc terms seen across brands
GLOSSARY_TO_ISO = {
    # === 301 Lockstitch (單針平車) ===
    'SN TOPSTITCH': '301',
    'SNTS': '301',
    'SN TS': '301',
    'SINGLE NEEDLE TOPSTITCH': '301',
    'SINGLE NEEDLE TOP STITCH': '301',
    'SN EDGESTITCH': '301',
    'SN EDGSTITCH': '301',      # typo variant
    'EDGESTITCH': '301',
    'EDGE STITCH': '301',
    'TOPSTITCH': '301',
    'TOP STITCH': '301',
    'LOCKSTITCH': '301',
    'LOCK STITCH': '301',
    'SINGLE NEEDLE': '301',     # when alone, usually 301
    'SNT': '301',
    'S.N.T.S': '301',
    'SNES': '301',              # single needle edge stitch
    'SN EDGE STITCH': '301',
    'FELLED SEAM': '301',       # felled seam uses lockstitch
    'FLAT FELLED': '301',
    'CLEAN FINISH': '301',      # clean finish typically lockstitch
    'TURN AND TURN': '301',     # turn and turn hem = lockstitch
    'TURNBACK': '301',
    'TURN BACK': '301',
    'NDL TURN BACK': '301',     # 5/8" NDL TURN BACK AT HEM
    'BARTACK': '301',           # bartacks are lockstitch

    # === 304 Lockstitch Zigzag ===
    'ZIGZAG': '304',
    'ZIG ZAG': '304',
    'ZIGZAG STITCH': '304',

    # === 401 Chainstitch (單針鏈縫) ===
    'CHAINSTITCH': '401',
    'CHAIN STITCH': '401',
    'SN CHAINSTITCH': '401',
    'SINGLE NEEDLE CHAINSTITCH': '401',
    'SN CS': '401',
    '1N 401': '401',

    # === 406 2-Needle Coverstitch (三本雙針) ===
    '2N STRADDLE STITCH': '406',
    '2N STRADDLE': '406',
    '2 NEEDLE STRADDLE': '406',
    '2N COVERSTITCH': '406',
    '2-NDL COVERSTITCH': '406',
    '2 NEEDLE COVERSTITCH': '406',
    '2N COVER STITCH': '406',
    'DN COVERSTITCH': '406',
    'COVERSTITCH': '406',       # default coverstitch = 406
    'COVER STITCH': '406',
    'CVRST': '406',             # DKS abbreviation
    '2N CVRST': '406',
    'BTTM CS': '406',           # KOH abbreviation
    '2N 406': '406',
    '2NDL COVERSTITCH': '406',
    # DNTS / DOUBLE NEEDLE: Fabric-dependent → handled in map_terminology_to_iso()
    # Knit = 401 (chainstitch double needle), Woven = 301 (lockstitch double needle)
    # Do NOT map to 406 — it's NOT coverstitch

    # === 407 3-Needle Bottom Coverstitch ===
    '3N COVERSTITCH': '407',
    '3 NEEDLE COVERSTITCH': '407',
    '407': '407',

    # === 504 3-Thread Overlock (三線拷克) ===
    'SERGE': '504',
    'SERGED': '504',
    '3 THREAD OVERLOCK': '504',
    'THREE THREAD OVERLOCK': '504',
    'OVEREDGE': '504',
    'OVEREGE': '504',           # typo
    '504 OVERLOCK': '504',

    # === 514 4-Thread Overlock (四線拷克) ===
    'OVERLOCK': '514',          # generic overlock = 514 default
    '4 THREAD OVERLOCK': '514',
    'FOUR THREAD OVERLOCK': '514',
    '514 OVERLOCK': '514',
    'MOCK SAFETY': '514',
    'MOCK SAFETY STITCH': '514',
    'SAFETY STITCH': '514',     # can be 516, but 514 more common for ONY

    # === 516 5-Thread Safety Stitch ===
    '5 THREAD SAFETY STITCH': '516',
    'SFTY ST': '516',
    '516 SAFETY': '516',

    # === 602 Single Turn Coverstitch ===
    'SINGLE TURN': '602',
    'SINGLE TURN 602': '602',

    # === 605 3-Needle 5-Thread Coverstitch (三針五線繃縫) ===
    '3N STRADDLE': '605',
    '3 NEEDLE STRADDLE': '605',
    '605 STRADDLE': '605',
    '3N 5TH COVERSTITCH': '605',
    'LAPPED SEAM': '605',

    # === 607 4-Needle 6-Thread Flatseam (四針六線併縫) ===
    'FLATLOCK': '607',
    'FLAT LOCK': '607',
    'FLATSEAM': '607',
    'FLAT SEAM': '607',
    '4NDL FLATLOCK': '607',
    '4 NEEDLE FLATLOCK': '607',
    '4N6T FLATLOCK': '607',
    '4N 6TH': '607',
    'FLATSEAMER': '607',

    # === Special / Non-sewing ===
    'BONDED': 'BONDED',
    'HEAT SEAL': 'BONDED',
    'LAMINATE': 'BONDED',
    'LASER CUT': 'LASER_CUT',
    'RAW EDGE': 'RAW_EDGE',
    'BINDING': 'BINDING',       # need context for ISO
    'CONTRAST BINDING': 'BINDING',
}

# ONY default seam rules
ONY_DEFAULTS = {
    'athletic_knit': '607',     # "body seams are 607 unless otherwise noted"
    'casual_knit': '514',       # "body seams are 514 unless otherwise noted"
}

# L1 zone name mapping (English → 38-code)
ZONE_TO_L1 = {
    # Neck area
    'NECK': 'NK',
    'NECKLINE': 'NK',
    'NECKBAND': 'NK',
    'NECK BAND': 'NK',
    'COLLAR': 'NK',
    'BACK NECK': 'BN',
    'BACK NECK TAPE': 'BN',
    'BNT': 'BN',
    'FRONT NECK': 'NK',

    # Shoulder
    'SHOULDER': 'SH',
    'SHOULDER SEAM': 'SH',

    # Armhole / Sleeve
    'ARMHOLE': 'AH',
    'ARMHOLES': 'AH',
    'ARM HOLE': 'AH',
    'A/H': 'AH',
    'AH SEAM': 'AH',
    'ARM OPENING': 'AH',
    'SET IN SLEEVE': 'AH',
    'SLEEVE': 'SL',
    'SLEEVE SEAM': 'SL',
    'SLEEVE CUFF': 'SA',       # sleeve attach/cuff
    'CUFF': 'SA',
    'SLEEVE OPENING': 'SA',
    'SLEEVE HEM': 'SA',

    # Body seams
    'SIDE SEAM': 'SR',
    'SIDESEAM': 'SR',
    'SS': 'SR',
    'BODY SEAM': 'SR',

    # Waistband
    'WAISTBAND': 'WB',
    'WAIST BAND': 'WB',
    'WB': 'WB',
    'ELASTIC WAISTBAND': 'WB',

    # Bottom / Hem
    'BOTTOM HEM': 'HL',
    'HEM': 'HL',
    'BOTTOM BAND': 'HL',
    'BTM HEM': 'HL',
    'HEMLINE': 'HL',
    'SHIRTTAIL': 'HL',

    # Pocket
    'POCKET': 'PK',
    'FRONT POCKET': 'PK',
    'BACK POCKET': 'PK',
    'PKT': 'PK',
    'HAND POCKET': 'PK',
    'PALM SIDE POCKET': 'PK',
    'WELT POCKET': 'PK',

    # Inseam / Rise
    'INSEAM': 'PS',
    'IN SEAM': 'PS',
    'RISE': 'RS',
    'CROTCH': 'RS',
    'GUSSET': 'RS',

    # Zipper
    'ZIPPER': 'ZP',
    'ZIP': 'ZP',
    'FLY': 'FY',
    'CF ZIPPER': 'ZP',

    # Placket
    'PLACKET': 'PL',
    'CF PLACKET': 'PL',

    # Hood
    'HOOD': 'HD',

    # Yoke
    'YOKE': 'OT',
    'BACK YOKE': 'OT',

    # Drawcord
    'DRAWCORD': 'DC',
    'DRAWSTRING': 'DC',

    # Leg opening
    'LEG OPENING': 'LO',

    # Label
    'LABEL': 'LB',
    'MAIN LABEL': 'LB',

    # Binding / Tape
    'NECK BINDING': 'NK',
    'ARMHOLE BINDING': 'AH',
}


# ============================================================
# PART 2: CALLOUT PAGE DETECTOR
# ============================================================

def detect_callout_pages(pdf_path):
    """
    Find Construction Callout pages in a Centric 8 PDF.

    Strategy:
    1. Find pages with "BOM Review/Callouts" or "CALLOUT" in text layer
    2. Among those, identify IMAGE-BASED callout pages (word count < 40)
       vs TEXT-BASED pages (word count > 40, has actual content)
    3. Return page indices of image-based callout pages (need VLM)

    Returns: list of (page_index, page_type) where page_type is 'image' or 'text'
    """
    import fitz
    doc = fitz.open(pdf_path)
    results = []

    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text()
        text_upper = text.upper()

        # Must be a callout/BOM review page
        if not any(kw in text_upper for kw in ['CALLOUT', 'BOM REVIEW', 'DESIGN BOM']):
            continue

        # Skip pure metadata pages (long text = property tables)
        word_count = len(text.split())

        if word_count < 40:
            # Low word count = annotations are in graphic layer → need VLM
            results.append((i, 'image'))
        else:
            # High word count = some text is extractable
            # Check if it has actual construction terms (not just metadata)
            has_construction = any(kw in text_upper for kw in [
                'STITCH', 'SEAM', 'OVERLOCK', 'EDGESTITCH', 'TOPSTITCH',
                'BINDING', 'FLATLOCK', 'COVERSTITCH', 'HEM', 'BARTACK',
                'CONSTRUCTION CALLOUT', 'ADDITIONAL DETAIL'
            ])
            if has_construction:
                results.append((i, 'text'))
            else:
                results.append((i, 'image'))

    doc.close()
    return results


def render_callout_pages(pdf_path, page_indices, output_dir, design_id):
    """Render callout pages as PNG images for VLM processing."""
    import fitz
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    rendered = []

    for pg_idx, pg_type in page_indices:
        page = doc[pg_idx]
        mat = fitz.Matrix(3, 3)  # 216 DPI — good balance of readability vs size
        pix = page.get_pixmap(matrix=mat)
        out_path = os.path.join(output_dir, f"{design_id}_p{pg_idx+1}.png")
        pix.save(out_path)
        rendered.append({
            'design_id': design_id,
            'pdf': os.path.basename(pdf_path),
            'page': pg_idx + 1,
            'page_type': pg_type,
            'image': out_path,
            'size': f"{pix.width}x{pix.height}",
        })

    doc.close()
    return rendered


# ============================================================
# PART 3: VLM PROMPT TEMPLATE
# ============================================================

VLM_PROMPT = """You are analyzing a Construction Callout page from a Centric 8 Techpack PDF for a garment.

Extract ALL zone-level construction annotations visible on this page.

For each annotation, provide:
1. **ZONE**: The garment zone name (e.g., NECK, ARMHOLE, SHOULDER, SIDE SEAM, HEM, etc.)
2. **CONSTRUCTION**: The exact construction description text as written
3. **ISO** (if explicitly stated): Any ISO stitch code mentioned (e.g., 301, 406, 514, 607)

Output as JSON array:
```json
[
  {"zone": "NECK", "construction": "SN EDGESTITCH, 1/8\" M", "iso": null},
  {"zone": "ARMHOLES", "construction": "1/4\" 2N STRADDLE STITCH", "iso": null},
  {"zone": "BOTTOM HEM", "construction": "607 FLATSEAM", "iso": "607"}
]
```

Rules:
- Include ALL visible annotations, even partial ones
- Use the zone name exactly as shown on the garment sketch
- If a note says "ALL SEAMS ARE XXX", record it as zone="ALL SEAMS"
- If no ISO code is explicitly written, set iso to null
- Include measurements (e.g., 1/4", 1/8") in the construction text
- Include stitch abbreviations as-is (SNTS, 2NTS, SN, DN, etc.)
- If the page has no construction annotations (just a sketch or photo), return []
"""


# ============================================================
# PART 4: GLOSSARY MAPPING
# ============================================================

def map_terminology_to_iso(construction_text, fabric=None):
    """
    Map GAP/ONY construction terminology to ISO code.

    Uses longest-match-first strategy to avoid partial matches.
    E.g., "2N STRADDLE STITCH" should match 406, not just "STITCH" → something else.

    fabric='Knit'|'Woven' for fabric-dependent terms (DNTS, DOUBLE NEEDLE).
    """
    text_upper = construction_text.upper().strip()

    # First: check if ISO code is explicitly stated in text
    iso_match = re.search(r'\b(301|304|401|406|407|501|503|504|514|515|516|602|605|607)\b', text_upper)
    if iso_match:
        return iso_match.group(1)

    # Fabric-dependent terms (must check BEFORE generic Glossary)
    # DNTS / DOUBLE NEEDLE: Knit=401, Woven=301 — NOT 406 coverstitch
    if any(t in text_upper for t in ['DNTS', 'DOUBLE NEEDLE TOP STITCH', 'DN TOPSTITCH',
                                      'DN TOP STITCH', 'DOUBLE NEEDLE TS']):
        if fabric and fabric.upper() == 'KNIT':
            return '401'
        else:
            return '301'  # Woven default, also fallback when fabric unknown

    # Second: longest-match Glossary lookup
    # Sort by length descending so longer terms match first
    sorted_terms = sorted(GLOSSARY_TO_ISO.keys(), key=len, reverse=True)

    for term in sorted_terms:
        if term in text_upper:
            iso = GLOSSARY_TO_ISO[term]
            if iso not in ('BONDED', 'LASER_CUT', 'RAW_EDGE', 'BINDING'):
                return iso

    return None


def map_zone_to_l1(zone_name):
    """Map zone name from callout to L1 38-code."""
    zone_upper = zone_name.upper().strip()

    # Direct lookup
    if zone_upper in ZONE_TO_L1:
        return ZONE_TO_L1[zone_upper]

    # Partial match
    sorted_zones = sorted(ZONE_TO_L1.keys(), key=len, reverse=True)
    for z in sorted_zones:
        if z in zone_upper:
            return ZONE_TO_L1[z]

    return None


def process_vlm_output(vlm_json, design_id, fabric=None):
    """
    Process VLM extraction output → structured zone-ISO mapping.

    Input: list of {zone, construction, iso} from VLM
    Output: {l1_code: {iso: source_text}} per zone
    fabric: 'Knit'|'Woven' for fabric-dependent Glossary terms (DNTS etc.)
    """
    result = {}
    all_seams_iso = None

    for item in vlm_json:
        zone = item.get('zone', '')
        construction = item.get('construction', '')
        explicit_iso = item.get('iso')

        # Handle "ALL SEAMS" default
        if 'ALL SEAM' in zone.upper() or 'ALL BODY' in zone.upper():
            iso = explicit_iso or map_terminology_to_iso(construction, fabric=fabric)
            if iso:
                all_seams_iso = iso
            continue

        # Map zone to L1
        l1 = map_zone_to_l1(zone)
        if not l1:
            continue

        # Map construction to ISO
        iso = explicit_iso or map_terminology_to_iso(construction, fabric=fabric)
        if iso:
            result[l1] = {
                'iso': iso,
                'zone_name': zone,
                'construction': construction,
                'source': 'explicit' if explicit_iso else 'glossary',
            }

    # Apply "ALL SEAMS" default to unspecified zones
    if all_seams_iso:
        default_zones = ['SR', 'SH', 'AH', 'PS', 'RS', 'SL']
        for z in default_zones:
            if z not in result:
                result[z] = {
                    'iso': all_seams_iso,
                    'zone_name': f'(default from ALL SEAMS)',
                    'construction': f'ALL SEAMS {all_seams_iso}',
                    'source': 'default_rule',
                }

    return result


# ============================================================
# PART 5: BATCH PROCESSING
# ============================================================

def find_pdfs_for_designs(design_ids, search_dirs=None):
    """Find original PDF files for a list of design IDs."""
    if search_dirs is None:
        search_dirs = [
            f"{BASE}/2024", f"{BASE}/2025", f"{BASE}/2026"
        ]

    design_pdfs = defaultdict(list)

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            if '_parsed' in root:
                continue
            for fname in files:
                if not fname.endswith('.pdf'):
                    continue
                for did in design_ids:
                    if did in fname or did in root:
                        fpath = os.path.join(root, fname)
                        design_pdfs[did].append(fpath)
                        break

    return design_pdfs


def detect_and_render_batch(design_ids, output_dir):
    """
    Step 1: For each design, find PDF → detect callout pages → render images.
    Returns manifest of all rendered images for VLM processing.
    """
    os.makedirs(output_dir, exist_ok=True)
    img_dir = os.path.join(output_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)

    # Find PDFs
    print("Finding PDFs...")
    design_pdfs = find_pdfs_for_designs(design_ids)
    print(f"  Found PDFs for {len(design_pdfs)}/{len(design_ids)} designs")

    manifest = []

    for did in sorted(design_ids):
        pdfs = design_pdfs.get(did, [])
        if not pdfs:
            print(f"  {did}: no PDF found")
            continue

        # Use the first PDF (usually the main one)
        # Prefer files with "Concept-en" or "Adopted" in name
        best_pdf = pdfs[0]
        for p in pdfs:
            bn = os.path.basename(p)
            if 'Adopted-en' in bn or 'Concept-en' in bn:
                best_pdf = p
                break

        # Detect callout pages
        try:
            pages = detect_callout_pages(best_pdf)
        except Exception as e:
            print(f"  {did}: error detecting pages: {e}")
            continue

        if not pages:
            print(f"  {did}: no callout pages found")
            continue

        # Render
        rendered = render_callout_pages(best_pdf, pages, img_dir, did)
        manifest.extend(rendered)

        img_types = [r['page_type'] for r in rendered]
        print(f"  {did}: {len(rendered)} callout pages ({', '.join(img_types)})")

    # Save manifest
    manifest_path = os.path.join(output_dir, 'manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest saved: {manifest_path}")
    print(f"Total images: {len(manifest)}")

    return manifest


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='VLM Construction Callout Pipeline')
    parser.add_argument('--detect-only', action='store_true',
                       help='Step 1: detect callout pages and render images')
    parser.add_argument('--map-iso', action='store_true',
                       help='Step 2: apply Glossary mapping to VLM extracts')
    parser.add_argument('--design', type=str, help='Process single design ID')
    parser.add_argument('--pilot', action='store_true',
                       help='Process pilot batch of 20 designs')
    args = parser.parse_args()

    if args.detect_only or args.pilot:
        # Load classifications for pilot selection
        with open(CLASS_FILE) as f:
            cls_map = json.load(f)

        if args.design:
            pilot_ids = [args.design]
        elif args.pilot:
            # Select diverse 20-design pilot
            pilot_ids = select_pilot_batch(cls_map, n=20)
        else:
            print("Specify --design or --pilot")
            sys.exit(1)

        detect_and_render_batch(pilot_ids, OUT_DIR)

    elif args.map_iso:
        # Read VLM raw extracts and apply Glossary mapping
        raw_path = os.path.join(OUT_DIR, 'vlm_raw_extracts.json')
        if not os.path.exists(raw_path):
            print(f"Error: {raw_path} not found. Run VLM extraction first.")
            sys.exit(1)

        with open(raw_path) as f:
            raw = json.load(f)

        results = {}
        for did, vlm_data in raw.items():
            fabric = vlm_data.get('fabric')
            mapped = process_vlm_output(vlm_data.get('callouts', []), did, fabric=fabric)
            results[did] = mapped

        out_path = os.path.join(OUT_DIR, 'vlm_callout_extracts.json')
        with open(out_path, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Mapped results: {out_path}")
        print(f"Designs: {len(results)}")


def select_pilot_batch(cls_map, n=20):
    """Select diverse pilot batch covering different GT, gender, fabric combos."""
    import random

    buckets = defaultdict(list)
    for did, c in cls_map.items():
        gt = c.get('gt', 'UNKNOWN')
        gender = c.get('gender', 'UNKNOWN')
        fabric = c.get('fabric', 'Unknown')
        key = f"{fabric}|{gt}"
        buckets[key].append(did)

    selected = []
    # Prioritize: Knit TOP, Woven TOP, Knit BOTTOM, Woven BOTTOM, DRESS, others
    priority_keys = [
        'Knit|TOP', 'Woven|TOP', 'Knit|BOTTOM', 'Woven|BOTTOM',
        'Knit|DRESS', 'Woven|DRESS', 'Knit|SHORTS', 'Knit|OUTERWEAR',
        'Woven|OUTERWEAR', 'Knit|LEGGINGS', 'Knit|SET',
    ]

    for key in priority_keys:
        if key in buckets and len(selected) < n:
            pool = buckets[key]
            pick = min(3, len(pool), n - len(selected))
            selected.extend(random.sample(pool, pick))

    # Fill remaining from any bucket
    all_remaining = [d for b in buckets.values() for d in b if d not in selected]
    remaining_need = n - len(selected)
    if remaining_need > 0:
        selected.extend(random.sample(all_remaining, min(remaining_need, len(all_remaining))))

    return selected[:n]
