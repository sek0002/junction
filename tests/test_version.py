"""Release increments and server-rendered version labels stay consistent."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.main import app, home
from app.version import VERSION

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bump_version', ROOT / 'scripts' / 'bump_version.py')
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


class VersionTests(unittest.TestCase):
    def test_page_labels_and_api_share_release_version(self):
        html = home().body.decode('utf8')
        self.assertEqual(html.count(f'>v{VERSION}</span>'), 2)
        self.assertNotIn('__JUNCTION_VERSION__', html)
        self.assertEqual(app.version, VERSION)
        self.assertEqual(app.openapi()['info']['version'], VERSION)

    def test_release_increments_reset_lower_components(self):
        for part, expected in [('patch', '2.3.10'), ('minor', '2.4.0'), ('major', '3.0.0')]:
            with self.subTest(part=part), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'version.py'
                path.write_text('# Keep this comment.\nVERSION = "2.3.9"\n')
                self.assertEqual(bump.bump_version(part, path), expected)
                self.assertEqual(path.read_text(), f'# Keep this comment.\nVERSION = "{expected}"\n')

    def test_invalid_versions_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'version.py'
            source = 'VERSION = "invalid"\n'
            path.write_text(source)
            with self.assertRaises(ValueError):
                bump.bump_version('patch', path)
            self.assertEqual(path.read_text(), source)


if __name__ == '__main__':
    unittest.main()
