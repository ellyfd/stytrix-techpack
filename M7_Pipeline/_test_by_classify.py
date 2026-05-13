import sys
sys.path.insert(0, 'scripts')
import fitz
from page_classifier import classify_page

p = 'tp_samples_v2/306185_SD3463/TPK24100226392-S26_SD3463_DEVELOPMENT TP_12-18-24.pdf'
doc = fitz.open(p)
for pg_idx in range(len(doc)):
    pg = doc[pg_idx]
    ptype, ev = classify_page(pg, client_code='BY')
    if ptype != 'junk':
        reason = ev.get('reason', '-')
        print('pg' + str(pg_idx+1) + ': ' + ptype + ' (reason=' + str(reason) + ')')
doc.close()
