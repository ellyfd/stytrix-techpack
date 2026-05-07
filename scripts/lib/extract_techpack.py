"""
extract_techpack.py — Centric 8 ONY Techpack PDF → structured MC + POM data.

Extracts:
 - Page-1/2 metadata (Design Number, Description, Brand/Division, Department, etc.)
 - All Measurement Chart (MC) blocks with body type
 - All POM rows with size values

Output per PDF: {
  "_source_path": str,
  "design_number": str,
  "description": str,
  "brand_division": str,
  "department": str,
  "bom_category": str,
  "sub_category": str,
  "collection": str,
  "mcs": [
    {
      "mc_key": str,   # e.g. "D87501 MC Makalot - M Final"
      "body_type": str, # MISSY / PLUS / PETITE / TALL / MATERNITY / UNKNOWN
      "status": str,    # Final / IN WORK / Sample
      "sizes": [str],   # e.g. ["XXS","XS","S","M","L","XL","XXL"]
      "poms": [
        {"POM_Code": str, "POM_Name": str, "sizes": {size: value_str, ...}}
      ]
    }
  ]
}
"""

import pdfplumber
import re
import os

# ── Body type detection from MC key string ──
_BT_PATTERNS = [
    (r'\b2X\b', 'PLUS'), (r'\b3X\b', 'PLUS'), (r'\b4X\b', 'PLUS'),
    (r'\bPLUS\b', 'PLUS'),
    (r'\bPETITE\b', 'PETITE'),
    (r'\bTALL\b', 'TALL'),
    (r'\bMATERNITY\b', 'MATERNITY'),
    (r'\b-\s*M\s', 'MISSY'),        # "- M Final" or "- M IN WORK"
    (r'\b-\s*M$', 'MISSY'),
]

def detect_body_type(mc_key: str) -> str:
    for pat, bt in _BT_PATTERNS:
        if re.search(pat, mc_key, re.IGNORECASE):
            return bt
    return 'MISSY'  # ONY default is MISSY when no explicit body type marker

def detect_status(mc_key: str) -> str:
    low = mc_key.lower()
    if 'final' in low:
        return 'Final'
    if 'in work' in low:
        return 'IN WORK'
    if 'sample' in low:
        return 'Sample'
    return 'Unknown'

# ── Page-1/2 metadata extraction (layout-aware) ──
_META_FIELDS = {
    'Design Number': r'(?:Design\s*Number|Style\s*#)\s*[:\-]?\s*(\S+)',
    'Brand/Division': r'Brand/Division\s+(.+?)(?:\n|$)',
    'Department': r'Department\s+(.+?)(?:\n|$)',
    'Collection': r'Collection\s+(.+?)(?:\n|$)',
    'BOM Category': r'(?:BOM\s*)?Category\s+(.+?)(?:\n|$)',
    'Sub-Category': r'Sub[\s-]*Category\s+(.+?)(?:\n|$)',
}

def extract_page1_meta(pdf) -> dict:
    """Extract metadata from page 1 (and page 2 as fallback).
    Uses both plain text (for header) and layout text (for tabular fields).
    """
    meta = {}
    pages_to_check = min(3, len(pdf.pages))

    for pi in range(pages_to_check):
        text = pdf.pages[pi].extract_text() or ''

        if pi == 0:
            # Design number + description from first line:
            # "D87501 SPD SMOCKED SHOULDER PEPLUM BLOUSE 000842464 Adopted"
            header_match = re.match(r'([A-Z]?\d{4,6})\s+(.+?)\s+(\d{9,})\s', text)
            if header_match:
                meta['design_number'] = header_match.group(1)
                meta['description'] = header_match.group(2).strip()

        # Extract tabular fields from page tables (key-value pairs)
        tables = pdf.pages[pi].extract_tables()
        for t in tables:
            if not t:
                continue
            for row in t:
                if not row or len(row) < 2:
                    continue
                # Clean key: collapse newlines
                key = ' '.join(str(row[0] or '').split()).strip()
                val = ' '.join(str(row[1] or '').split()).strip()
                if not key or not val:
                    continue
                key_low = key.lower()
                if 'brand/division' in key_low and 'Brand/Division' not in meta:
                    meta['Brand/Division'] = val
                elif key_low == 'department' and 'Department' not in meta:
                    meta['Department'] = val
                elif key_low == 'collection' and 'Collection' not in meta:
                    meta['Collection'] = val
                elif key == 'Category' and 'BOM Category' not in meta:
                    meta['BOM Category'] = val
                elif 'sub' in key_low and ('category' in key_low or 'type' in key_low):
                    if 'Sub-Category' not in meta:
                        meta['Sub-Category'] = val
                elif key_low == 'item type' and 'Item Type' not in meta:
                    meta['Item Type'] = val
                elif key_low == 'design number' and 'design_number' not in meta:
                    meta['design_number'] = val
                elif 'design sub' in key_low and 'Design Type' not in meta:
                    meta['Design Type'] = val
                elif key_low == 'flow' and 'Flow' not in meta:
                    meta['Flow'] = val

        # Also try regex on plain text as fallback
        for field, pattern in _META_FIELDS.items():
            if field not in meta or not meta[field]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val and val not in ('', '-'):
                        meta[field] = val

    return meta

# ── MC + POM extraction ──
_SIZE_LABELS = {'XXS','XS','S','M','L','XL','XXL','2X','3X','4X',
                '0','2','4','6','8','10','12','14','16','18','20',
                '22','24','26','28','30','32','34','36',
                '2T','3T','4T','5T','6-7','8','10-12','14-16','18-20'}

def _clean_pom_code(raw: str) -> str:
    """Clean POM code: uppercase, strip whitespace."""
    if not raw:
        return ''
    code = raw.strip().upper()
    # Remove trailing description fragments that leaked
    code = code.split('\n')[0].strip()
    # Must match pattern: letter + digits + optional .digits
    m = re.match(r'^([A-Z]\d+(?:\.\d+)?)', code)
    return m.group(1) if m else ''

def _clean_value(raw: str) -> str:
    """Clean a size value cell: handle fractions, newlines."""
    if not raw:
        return ''
    # Join newlines, collapse whitespace
    val = ' '.join(raw.split())
    val = val.strip()
    # Skip checkmarks and empty
    if val in ('', '-', '\ue5ca', '✓'):
        return ''
    return val

def extract(pdf_path: str) -> dict:
    """Main extraction function."""
    result = {
        '_source_path': pdf_path,
        'design_number': '',
        'description': '',
        'brand_division': '',
        'department': '',
        'bom_category': '',
        'sub_category': '',
        'collection': '',
        'item_type': '',
        'design_type': '',
        'flow': '',
        'mcs': [],
    }

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        result['_error'] = str(e)
        return result

    try:
        # Step 1: Page-1 metadata
        meta = extract_page1_meta(pdf)
        result['design_number'] = meta.get('design_number', '')
        result['description'] = meta.get('description', '')
        result['brand_division'] = meta.get('Brand/Division', '')
        result['department'] = meta.get('Department', '')
        result['bom_category'] = meta.get('BOM Category', '')
        result['sub_category'] = meta.get('Sub-Category', '')
        result['collection'] = meta.get('Collection', '')
        result['item_type'] = meta.get('Item Type', '')
        result['design_type'] = meta.get('Design Type', '')
        result['flow'] = meta.get('Flow', '')

        # Step 2: Find all MC pages and group by MC key
        # KEY: Centric 8 renders each MC in two display modes:
        #   "Grade Rule Display: Increment" — base size = measurement, others = grading deltas
        #   "Grade Rule Display: Absolute"  — all sizes = absolute measurements
        # We ONLY want ABSOLUTE rows. Increment rows cause noise in median analysis.
        mc_pages = {}  # mc_key -> list of (page_idx, table_data)
        current_mc_key = None

        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ''

            if 'Measurement Chart' not in text:
                continue

            # Try to extract MC key
            mc_match = re.search(r'(D\d+\s+MC\s+[^\n]+?)(?:\s+IN WORK|\s+Final|\s+Sample)', text)
            if mc_match:
                raw_key = mc_match.group(0).strip()
                # Clean: remove "Supplier ..." suffix
                raw_key = re.sub(r'\s+Supplier\s+.*', '', raw_key)
                # Remove timestamp
                raw_key = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}.*', '', raw_key)
                current_mc_key = raw_key

            if not current_mc_key:
                # Fallback: use page text to find any MC reference
                mc_any = re.search(r'(D\d+\s+MC\s+\S+)', text)
                if mc_any:
                    current_mc_key = mc_any.group(1)

            if not current_mc_key:
                continue

            # Find POM table on this page
            tables = page.extract_tables()
            pom_table = None
            for t in tables:
                if not t or len(t) < 2:
                    continue
                hdr = t[0]
                if hdr and len(hdr) > 5:
                    h0 = str(hdr[0] or '').strip()
                    if 'POM' in h0 or h0 in ('POM\nName', 'POM Name'):
                        pom_table = t
                        break

            if not pom_table:
                continue

            # Detect display mode from footer/pagination row and page text
            display_mode = 'unknown'
            # Check table rows
            for row in pom_table:
                full_row = ' '.join(str(c or '') for c in row)
                if 'Grade Rule Display' in full_row or 'Displaying' in full_row:
                    if 'Increment' in full_row:
                        display_mode = 'increment'
                        break
                    elif re.search(r'Display:\s*Ab', full_row):
                        display_mode = 'absolute'
                        break
            # Fallback: check page text
            if display_mode == 'unknown':
                if re.search(r'Grade Rule Display:\s*In', text):
                    display_mode = 'increment'
                elif re.search(r'Grade Rule Display:\s*Ab', text):
                    display_mode = 'absolute'

            # SKIP INCREMENT pages — they contain grading deltas, not measurements
            if display_mode == 'increment':
                continue

            if current_mc_key not in mc_pages:
                mc_pages[current_mc_key] = {'header': pom_table[0], 'rows': []}

            # Add non-header, non-pagination rows
            for row in pom_table[1:]:
                cell0 = str(row[0] or '').strip()
                if cell0 and 'Displaying' not in cell0:
                    mc_pages[current_mc_key]['rows'].append(row)

        # Step 3: Convert mc_pages to structured output
        for mc_key, data in mc_pages.items():
            header = data['header']
            rows = data['rows']

            # Determine size columns from header
            sizes = []
            size_col_indices = []
            for ci, h in enumerate(header):
                h_clean = str(h or '').strip().replace('\n', ' ')
                # Check if it's a known size label
                if h_clean in _SIZE_LABELS:
                    sizes.append(h_clean)
                    size_col_indices.append(ci)

            mc_entry = {
                'mc_key': mc_key,
                'body_type': detect_body_type(mc_key),
                'status': detect_status(mc_key),
                'sizes': sizes,
                'poms': [],
            }

            # Also find tolerance columns (Tol Fraction - / +)
            tol_neg_idx = None
            tol_pos_idx = None
            for ci, h in enumerate(header):
                h_clean = str(h or '').replace('\n', ' ').strip().lower()
                if 'tol' in h_clean and '(-)' in h_clean or 'tol' in h_clean and '-' in h_clean and 'fraction' in h_clean:
                    tol_neg_idx = ci
                elif 'tol' in h_clean and '(+)' in h_clean or 'tol' in h_clean and '+' in h_clean and 'fraction' in h_clean:
                    tol_pos_idx = ci

            for row in rows:
                pom_code = _clean_pom_code(str(row[0] or ''))
                if not pom_code:
                    continue

                # Skip comment/note rows (icon rows like ✚ or \ue5da)
                cell0_raw = str(row[0] or '').strip()
                if cell0_raw and cell0_raw[0] in ('\ue5da', '✚', '►', '▸'):
                    continue

                pom_name = str(row[1] or '').replace('\n', ' ').strip() if len(row) > 1 else ''

                size_vals = {}
                for si, col_idx in enumerate(size_col_indices):
                    if col_idx < len(row):
                        val = _clean_value(str(row[col_idx] or ''))
                        if val and si < len(sizes):
                            size_vals[sizes[si]] = val

                # Extract tolerance if available
                tol = {}
                if tol_neg_idx is not None and tol_neg_idx < len(row):
                    tv = _clean_value(str(row[tol_neg_idx] or ''))
                    if tv:
                        tol['neg'] = tv
                if tol_pos_idx is not None and tol_pos_idx < len(row):
                    tv = _clean_value(str(row[tol_pos_idx] or ''))
                    if tv:
                        tol['pos'] = tv

                pom_entry = {
                    'POM_Code': pom_code,
                    'POM_Name': pom_name,
                    'sizes': size_vals,
                }
                if tol:
                    pom_entry['tolerance'] = tol

                mc_entry['poms'].append(pom_entry)

            # Deduplicate POMs: keep first occurrence of each POM code
            # (multiple Absolute pages for different body types can merge into one mc_key)
            seen_codes = set()
            deduped_poms = []
            for p in mc_entry['poms']:
                if p['POM_Code'] not in seen_codes:
                    seen_codes.add(p['POM_Code'])
                    deduped_poms.append(p)
            mc_entry['poms'] = deduped_poms

            # Only add MCs that have POM data AND detected size columns
            # (skip Sample Review tables that have Target/Sample/Actual columns instead)
            if mc_entry['poms'] and mc_entry['sizes']:
                result['mcs'].append(mc_entry)

    except Exception as e:
        result['_error'] = str(e)
    finally:
        pdf.close()

    return result


if __name__ == '__main__':
    import json, sys
    path = sys.argv[1] if len(sys.argv) > 1 else '/sessions/stoic-magical-curie/mnt/ONY/2026/1/ONY_639029136810011754.pdf'
    result = extract(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
