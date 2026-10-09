#!/usr/bin/env python3
"""Regenerate the standalone HTML dashboard from a saved statistics report."""
import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
TOKEN = '__REPORT_DATA__'


def build(template_path=None, stats_path=None, output_path=None):
    template_path = pathlib.Path(template_path or ROOT / 'dashboard.html')
    stats_path = pathlib.Path(stats_path or ROOT / 'report/statistiche.json')
    output_path = pathlib.Path(output_path or ROOT / 'report/dashboard.html')
    template = template_path.read_text(encoding='utf-8')
    if template.count(TOKEN) != 1:
        raise ValueError(f'Il template deve contenere {TOKEN} esattamente una volta.')
    report = json.loads(stats_path.read_text(encoding='utf-8'))
    if not isinstance(report, dict) or not isinstance(report.get('years'), dict):
        raise ValueError('Il file statistiche non ha uno schema WhatsApp valido.')
    payload = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    html = template.replace(TOKEN, payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')
    return output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stats', default=str(ROOT / 'report/statistiche.json'))
    parser.add_argument('--output', default=str(ROOT / 'report/dashboard.html'))
    args = parser.parse_args()
    print(build(stats_path=args.stats, output_path=args.output))


if __name__ == '__main__':
    main()
