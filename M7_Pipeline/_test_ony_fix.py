import sys
sys.path.insert(0, 'scripts')
import fitz
from client_parsers import get_parser
parser = get_parser('ONY')
p = 'tp_samples_v2/307018_D1075_BOM806382/TPK25100232183-Fitted LL SNUG PJ Set-D1075 Fitted LL SNUG PJ Set 000806382 Concept-en.pdf'
doc = fitz.open(p)
total = 0
for pg_idx in range(len(doc)):
    pg = doc[pg_idx]
    txt = pg.get_text()
    mc = parser.parse_measurement_chart(pg, txt)
    if mc and mc.get('poms'):
        n = len(mc['poms'])
        total += n
        print('pg' + str(pg_idx+1) + ': ' + str(n) + ' POMs')
doc.close()
print('TOTAL: ' + str(total))
