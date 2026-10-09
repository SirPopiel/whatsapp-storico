import importlib.util
import json
import pathlib
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('build_dashboard', pathlib.Path(__file__).resolve().parents[1] / 'build_dashboard.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class DashboardBuildTests(unittest.TestCase):
    def test_embeds_stats_in_local_html(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            template = root / 'template.html'
            stats = root / 'stats.json'
            output = root / 'report/dashboard.html'
            template.write_text('<script>__REPORT_DATA__</script>', encoding='utf-8')
            stats.write_text(json.dumps({'years': {'2026': {}}, 'name': '</script>'}), encoding='utf-8')
            self.assertEqual(b.build(template, stats, output), output)
            rendered = output.read_text(encoding='utf-8')
            self.assertNotIn(b.TOKEN, rendered)
            self.assertIn('\\u003c/script>', rendered)

    def test_rejects_bad_template_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            template = root / 'template.html'
            stats = root / 'stats.json'
            template.write_text('<p>no placeholder</p>', encoding='utf-8')
            stats.write_text('{"years":{}}', encoding='utf-8')
            with self.assertRaises(ValueError):
                b.build(template, stats, root / 'out.html')
            template.write_text('__REPORT_DATA__', encoding='utf-8')
            stats.write_text('{"not_years":{}}', encoding='utf-8')
            with self.assertRaises(ValueError):
                b.build(template, stats, root / 'out.html')


if __name__ == '__main__':
    unittest.main()
