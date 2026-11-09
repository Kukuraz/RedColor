import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import pymupdf
from rp.document import _replace_file, FileLockedError, DocModel, SaveFailedError
from rp import formula

class SaveSafety(unittest.TestCase):
    def test_replace_failure_keeps_existing_file(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            src, dst = Path(d)/'new.pdf', Path(d)/'old.pdf'
            src.write_bytes(b'new contents'); dst.write_bytes(b'original contents')
            with mock.patch('os.replace', side_effect=PermissionError('locked')), mock.patch('time.sleep'):
                with self.assertRaises(FileLockedError): _replace_file(src,dst)
            self.assertEqual(dst.read_bytes(), b'original contents')
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ['new.pdf','old.pdf'])
    def test_replace_success(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            src, dst = Path(d)/'new.pdf', Path(d)/'old.pdf'
            src.write_bytes(b'new'); dst.write_bytes(b'old')
            _replace_file(src,dst)
            self.assertEqual(dst.read_bytes(),b'new')
    def test_invalid_overlay_cannot_save_silently(self):
        class Bad:
            def zValue(self): return 0
            def bake(self, page): raise ValueError('test failure')
        class Page:
            w=100; h=100
            def overlay_items(self): return [Bad()]
        class Doc: pages=[Page()]
        with self.assertRaisesRegex(SaveFailedError, 'test failure'):
            DocModel.build_overlay(Doc())
    def test_intermediate_formula_pdf_cache_released(self):
        f = formula.from_latex(r'\frac{1}{2}')
        cached = f.pdf_doc('#ff0000')
        self.assertFalse(cached.is_closed)
        formula.release_pdf_cache()
        self.assertTrue(cached.is_closed)
        self.assertEqual(f._pdf, {})
        new = f.pdf_doc('#ff0000')
        self.assertFalse(new.is_closed)
        formula.release_pdf_cache()

if __name__ == '__main__': unittest.main()
