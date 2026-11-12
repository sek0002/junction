"""Missing translation dependencies must not stop login or comparisons."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OptionalTranslationTests(unittest.TestCase):
    def test_app_starts_and_compares_without_biopython(self):
        script = r"""
import importlib.abc
import sys
class NoBio(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'Bio' or fullname.startswith('Bio.'):
            raise ModuleNotFoundError("No module named 'Bio'", name='Bio')
sys.meta_path.insert(0, NoBio())
from auth_client import AuthenticatedClient
from app.main import app
from app.comparison import compare_record
from app.coding_analysis import refresh_coding_results, BIO_AVAILABLE
assert not BIO_AVAILABLE
with AuthenticatedClient(app) as client:
    response = client.get('/api/summary')
    assert response.status_code == 200, response.text
    response = client.get('/api/workspace/comparisons')
    assert response.status_code == 200, response.text
    result = compare_record({'name':'Query','sequence':'ATGAAATAA','features':[]}, [], [], infer=False)
    assert result['query_coding_analysis']['available'] is False
    assert 'Biopython' in result['query_coding_analysis']['warnings'][0]
    match = {'aligned_reference':'ATGAAATAA','aligned_query':'ATGGAATAA','changes':[]}
    refresh_coding_results({'matches':[match]})
    assert match['coding_analysis']['available'] is False
"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'app.sqlite3'
            path.with_suffix('.sources.json').write_text('{"plate_files":[],"genbank_files":[]}')
            env = dict(os.environ, GOLDEN_GATE_DB=str(path))
            result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
