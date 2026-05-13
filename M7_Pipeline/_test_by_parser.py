import sys
sys.path.insert(0, 'scripts')
import fitz
from client_parsers import get_parser

parser = get_parser('BY')
p = 'tp_samples_v2/306185_SD3463/TPK24100226392-S26_SD3463_DEVELOPMENT TP_12-18-24.pdf'
doc = fitz.open(p)
total = 0
for pg_idx in range(len(doc)):
    pg = doc[pg_idx]
    txt = pg.get_text()
    mc = parser.parse_measurement_chart(pg, txt)
    if mc and mc.get('poms'):
        n = len(mc['poms'])
        total += n
        mode = mc.get('_parse_mode', '?')
        print('pg' + str(pg_idx+1) + ': ' + str(n) + ' POMs (mode=' + mode + ')')
        for pom in mc['poms'][:5]:
            print('    ' + pom.get('POM_Code') + ' | ' + pom.get('POM_Name', '?')[:35] + ' | tol=' + str(pom.get('tolerance', {})) + ' | sizes=' + str(pom.get('sizes', {})))
doc.close()
print('TOTAL: ' + str(total))
