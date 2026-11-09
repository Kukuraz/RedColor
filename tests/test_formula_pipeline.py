import base64, json, subprocess, sys, unittest
from pathlib import Path
from urllib.parse import quote
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'rust' / 'formula_helper.py'
SVG = "<svg xmlns='http://www.w3.org/2000/svg' width='24pt' height='16pt' viewBox='0 0 24 16'><path d='M0 0L24 16'/></svg>"

def request(obj):
    p = subprocess.run([sys.executable, str(HELPER)], input=json.dumps(obj, ensure_ascii=False).encode(), capture_output=True, check=True, timeout=60)
    return json.loads(p.stdout)

class FormulaPipelineTests(unittest.TestCase):
    def test_inline_svg_and_surrounding_text(self):
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(SVG.encode()).decode()
        result = request({'kind':'html','html':f'<p>До <img class="math" src="{uri}" alt="формула"> после</p>'})
        self.assertTrue(result['ok'], result)
        data=result['result']; self.assertEqual(len(data['formulas']),1)
        runs=data['blocks'][0][1]
        self.assertEqual([r[0] for r in runs], ['t','f','t'])
        self.assertIn('До',runs[0][1]); self.assertIn('после',runs[2][1])
        self.assertIn('<svg', next(iter(data['formulas'].values()))['svg'])
    def test_percent_encoded_svg(self):
        result=request({'kind':'html','html':'<img src="data:image/svg+xml,'+quote(SVG, safe='')+'">'})
        self.assertTrue(result['ok'], result); self.assertEqual(len(result['result']['formulas']),1)
    def test_failed_formula_is_not_silently_dropped(self):
        result=request({'kind':'html','html':'<p>Text<img src="data:image/svg+xml;base64,not-a-valid-svg" alt="x"></p>'})
        self.assertFalse(result['ok'])
    def test_complex_latex(self):
        for tex in [r'\sqrt{\frac{a_1+b^2}{c}}',r'\sum_{i=1}^{n} i^2',r'\int_0^\infty e^{-x^2}\,dx',r'\begin{cases} x+y=1 \\ x-y=2 \end{cases}']:
            with self.subTest(tex=tex):
                result=request({'kind':'latex','latex':tex})
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['result']['formula']['latex'],tex)
                self.assertIn('<svg',result['result']['formula']['svg'])

if __name__ == '__main__': unittest.main()
