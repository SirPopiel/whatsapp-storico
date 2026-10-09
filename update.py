#!/usr/bin/env python3
"""Export with WhatsApp Chat Exporter and rebuild a local, cumulative archive."""
import argparse, collections, csv, datetime as dt, hashlib, html, json, os, pathlib, plistlib, shutil, sqlite3, subprocess, sys
import re, unicodedata
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent
TZ = ZoneInfo('Europe/Madrid')
APPLE_EPOCH = 978307200
DESKTOP = pathlib.Path.home() / 'Library/Group Containers/group.net.whatsapp.WhatsApp.shared'
FINDER = pathlib.Path.home() / 'Library/Application Support/MobileSync/Backup'


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def snapshot_db(source, destination):
    # SQLite backup API includes committed WAL contents without changing the source.
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def exporter():
    exe = ROOT / '.venv/bin/wtsexporter'
    if not exe.exists():
        raise RuntimeError('Ambiente assente. Esegui ./aggiorna.command per installarlo.')
    return str(exe)


def discover():
    try:
        found = [p for p in FINDER.iterdir() if p.is_dir() and (p / 'Manifest.db').is_file()]
    except FileNotFoundError:
        found = []
    except PermissionError as e:
        raise RuntimeError('macOS blocca il backup Finder. Abilita Accesso completo al disco per Codex o Terminale, oppure usa --source desktop esplicitamente.') from e
    if len(found) > 1:
        raise RuntimeError('Più backup disponibili: scegli con --backup PERCORSO:\n' + '\n'.join(map(str, found)))
    return found[0] if found else None


def extract(args, run):
    backup = pathlib.Path(args.backup).expanduser().resolve() if args.backup else None
    mode = args.source
    if mode == 'auto':
        backup = backup or discover()
        if not backup:
            raise RuntimeError('Backup Finder assente: nessun ripiego automatico sul database Mac.')
        mode = 'backup'
    elif mode == 'backup' and not backup:
        backup = discover()
    if mode == 'json':
        if not args.json:
            raise RuntimeError('--source json richiede --json PERCORSO.')
        shutil.copy2(pathlib.Path(args.json).expanduser(), run / 'source.json')
        return mode, str(pathlib.Path(args.json).expanduser().resolve()), {}
    cmd = [exporter(), '--ios', '--json', str(run / 'source.json'), '--output', str(run / 'html'), '--txt', str(run / 'txt'), '--no-avatar', '--no-banner']
    audit = {}
    if mode == 'backup':
        if not backup or not (backup / 'Manifest.db').is_file():
            raise RuntimeError('Backup Finder valido non trovato. Specifica --backup PERCORSO.')
        with (backup / 'Manifest.plist').open('rb') as f:
            encrypted = plistlib.load(f).get('IsEncrypted')
        if encrypted is None:
            raise RuntimeError('IsEncrypted assente: verificare il backup prima di estrarlo.')
        if encrypted:
            subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'pip', 'install', 'git+https://github.com/KnugiHK/iphone_backup_decrypt@190d61c849045aded1863aa4bd1466e4d265f53d'], check=True)
            print('La password sarà richiesta dal programma nel Terminale; non viene salvata.')
        cmd += ['--backup', str(backup)]
        source_path = str(backup)
        audit['encrypted'] = bool(encrypted)
    elif mode == 'desktop':
        db = DESKTOP / 'ChatStorage.sqlite'
        if not db.is_file():
            raise RuntimeError('Database WhatsApp del Mac assente. Fornisci un backup Finder con --backup.')
        target = run / 'ChatStorage.sqlite'
        snapshot_db(db, target)
        with sqlite3.connect(target) as c:
            audit['database_records'] = c.execute('SELECT count(*) FROM ZWAMESSAGE').fetchone()[0]
            audit['chat_metadata'] = {jid: {'individual': session_type == 0 and group_info is None} for jid, session_type, group_info in c.execute('SELECT ZCONTACTJID,ZSESSIONTYPE,ZGROUPINFO FROM ZWACHATSESSION') if jid}
        # Contacts are also copied consistently, never opened for writing.
        contacts = DESKTOP / 'ContactsV2.sqlite'
        if contacts.exists():
            snapshot_db(contacts, run / 'ContactsV2.sqlite')
            cmd += ['--wa', str(run / 'ContactsV2.sqlite')]
        cmd += ['--db', str(target)]
        source_path = str(db)
    else:
        raise RuntimeError('Sorgente non riconosciuta.')
    subprocess.run(cmd, cwd=run, check=True)
    if not (run / 'source.json').is_file():
        raise RuntimeError('Exporter terminato senza creare il JSON: controlla la password e il database.')
    return mode, source_path, audit


def load_export(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not data:
        raise ValueError('JSON senza conversazioni o formato non supportato.')
    for jid, chat in data.items():
        if not isinstance(chat, dict) or not isinstance(chat.get('messages'), dict):
            raise ValueError(f'Schema WhatsApp Chat Exporter non valido: {jid}')
    return data


def merge(data, db_path, provenance):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        c.execute('CREATE TABLE IF NOT EXISTS chats (jid TEXT PRIMARY KEY, name TEXT, individual INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS messages (jid TEXT, identity TEXT, payload TEXT, PRIMARY KEY(jid,identity))')
        before = c.execute('SELECT count(*) FROM messages').fetchone()[0]
        for jid, chat in data.items():
            known = provenance.get('chat_metadata', {}).get(jid, {}).get('individual')
            individual = known if known is not None else jid.endswith(('@s.whatsapp.net', '@lid'))
            c.execute('INSERT INTO chats VALUES (?,?,?) ON CONFLICT(jid) DO UPDATE SET name=coalesce(excluded.name,chats.name), individual=excluded.individual', (jid, chat.get('name'), int(individual)))
            occurrences = collections.Counter()
            for m in chat['messages'].values():
                ts = m.get('timestamp')
                if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                    raise ValueError(f'Timestamp mancante/non numerico in {jid}')
                if ts > 9999999999:
                    m = dict(m, timestamp=ts / 1000)
                if m.get('key_id'):
                    identity = 'key:' + str(m['key_id'])
                else:
                    fingerprint = json.dumps([m['timestamp'], m.get('from_me'), m.get('message_type'), m.get('data'), m.get('caption'), m.get('meta')], ensure_ascii=False, sort_keys=True)
                    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
                    occurrences[digest] += 1
                    identity = f'fallback:{digest}:{occurrences[digest]}'
                c.execute('INSERT INTO messages VALUES (?,?,?) ON CONFLICT(jid,identity) DO UPDATE SET payload=excluded.payload', (jid, identity, json.dumps(m, ensure_ascii=False)))
        after = c.execute('SELECT count(*) FROM messages').fetchone()[0]
        merged = {}
        for jid, name, individual in c.execute('SELECT jid,name,individual FROM chats ORDER BY jid'):
            merged[jid] = {'name': name or jid.split('@')[0], 'individual': bool(individual), 'messages': {key: json.loads(payload) for key, payload in c.execute('SELECT identity,payload FROM messages WHERE jid=? ORDER BY identity', (jid,))}}
    return merged, after - before


def normalize_contact_name(name):
    """Normalize casing/spacing without changing intentionally mixed-case brands."""
    value = ' '.join(unicodedata.normalize('NFKC', str(name or '')).split())
    for left, right in (("'", "'"), ('"', '"'), ('‘', '’'), ('“', '”')):
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            value = value[1:-1].strip()
            break
    if not value:
        return value
    letters = ''.join(ch for ch in value if ch.isalpha())
    if not letters or not (letters.islower() or letters.isupper()):
        return value
    def cap_part(part):
        return part[:1].upper() + part[1:].lower() if part else part
    return re.sub(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", lambda m: re.sub(r"(?<=[\-'’])([^\-'’]+)", lambda x: cap_part(x.group(1)), cap_part(m.group(0))), value, flags=re.UNICODE)


def contact_name_key(name):
    value = ' '.join(unicodedata.normalize('NFKC', str(name or '')).split())
    for left, right in (("'", "'"), ('"', '"'), ('‘', '’'), ('“', '”')):
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            value = value[1:-1].strip()
            break
    return value.casefold().strip(' .,!;:')


def infer_duplicate_name_aliases(chats):
    """Merge exact duplicate, multi-word personal labels; keep single-word labels separate."""
    groups = collections.defaultdict(list)
    for jid, chat in chats.items():
        if not chat.get('individual'):
            continue
        name = ' '.join(unicodedata.normalize('NFKC', str(chat.get('name') or '')).split())
        key = contact_name_key(name)
        words = re.findall(r'[^\W\d_]+', key, flags=re.UNICODE)
        if len(words) >= 2 and not any(ch.isdigit() for ch in name):
            groups[key].append(jid)
    aliases = {}
    audit = []
    for jids in groups.values():
        if len(jids) < 2:
            continue
        # Prefer a phone JID as the stable displayed identity, then a JID with more messages.
        canonical = sorted(jids, key=lambda jid: (not jid.endswith('@s.whatsapp.net'), -len(chats[jid].get('messages', {})), jid))[0]
        aliases.update({jid: canonical for jid in jids if jid != canonical})
        audit.append({'name': normalize_contact_name(chats[canonical].get('name')), 'canonical_jid': canonical, 'merged_jids': [jid for jid in jids if jid != canonical], 'chat_count': len(jids)})
    return aliases, len(audit), audit


def make_report(chats, first_year, last_year, aliases=None):
    aliases = aliases or {}
    override_path = ROOT / 'name_overrides.json'
    name_overrides = json.loads(override_path.read_text(encoding='utf-8')) if override_path.is_file() else {}
    local_override_path = ROOT / 'name_overrides.local.json'
    if local_override_path.is_file():
        name_overrides.update(json.loads(local_override_path.read_text(encoding='utf-8')))
    inferred_aliases, duplicate_name_groups, name_merge_groups = infer_duplicate_name_aliases(chats)
    effective_aliases = dict(inferred_aliases)
    effective_aliases.update(aliases)
    def canonical_jid(jid):
        target = jid
        seen = set()
        while target in effective_aliases and target not in seen:
            seen.add(target)
            target = effective_aliases[target]
        return target
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    all_times, individual_times, per_chat, quality = [], [], {}, collections.Counter()
    monthly = collections.defaultdict(lambda: [0, 0])
    for jid, chat in chats.items():
        all_times.extend(m['timestamp'] for m in chat['messages'].values() if m['timestamp'] <= now)
        if not chat['individual']:
            quality['excluded_chats'] += 1
            continue
        canonical = canonical_jid(jid)
        display_name = name_overrides.get(canonical) or name_overrides.get(jid) or normalize_contact_name(chat['name'])
        entry = per_chat.setdefault(canonical, {'jid': canonical, 'name': display_name, 'years': {}, 'seen': set()})
        if canonical == jid:
            entry['name'] = display_name
        for identity, m in chat['messages'].items():
            # Type 6 = system events. Do not exclude all meta: vCards are user messages.
            if m.get('message_type') == 6 or (m.get('meta') and m.get('message_type') is None):
                quality['excluded_system_records'] += 1
                continue
            if m['timestamp'] > now:
                quality['future_records'] += 1
                continue
            unique = 'key:' + str(m['key_id']) if m.get('key_id') else jid + ':' + identity
            if unique in entry['seen']:
                quality['alias_duplicate_records'] += 1
                continue
            entry['seen'].add(unique)
            individual_times.append(m['timestamp'])
            local_time = dt.datetime.fromtimestamp(m['timestamp'], TZ)
            year = local_time.year
            bucket = entry['years'].setdefault(year, [0, 0])
            direction = 0 if m.get('from_me') else 1
            bucket[direction] += 1
            monthly[local_time.strftime('%Y-%m')][direction] += 1
    if not all_times:
        raise ValueError('Nessun messaggio datato utilizzabile.')
    if not individual_times:
        raise ValueError('Nessun messaggio individuale utilizzabile.')
    first_individual = dt.datetime.fromtimestamp(min(individual_times), TZ)
    latest = dt.datetime.fromtimestamp(max(all_times), TZ)
    earliest = dt.datetime.fromtimestamp(min(all_times), TZ)
    result, previous = {}, {}
    for year in range(first_year - 1, last_year + 1):
        rows = []
        for jid, entry in per_chat.items():
            sent = sum(v[0] for y, v in entry['years'].items() if y <= year)
            received = sum(v[1] for y, v in entry['years'].items() if y <= year)
            if not sent + received:
                continue
            ys, yr = entry['years'].get(year, [0, 0])
            pys, pyr = entry['years'].get(year - 1, [0, 0])
            annual = ys + yr
            prev_annual = pys + pyr
            rows.append({'jid': jid, 'name': entry['name'], 'total': sent + received, 'sent': sent, 'received': received, 'annual': annual, 'annual_sent': ys, 'annual_received': yr, 'annual_change': annual - prev_annual, 'annual_growth_pct': round((annual / prev_annual - 1) * 100, 1) if prev_annual else None})
        rows.sort(key=lambda r: (-r['total'], r['jid']))
        for rank, row in enumerate(rows, 1):
            row['rank'] = rank
            old = previous.get(row['jid'])
            row['previous_rank'] = old['rank'] if old else None
            row['rank_change'] = old['rank'] - rank if old else None
            row['new_chat'] = old is None
            row['entered_top50'] = rank <= 50 and (old is None or old['rank'] > 50)
            row['entered_top30'] = rank <= 30 and (old is None or old['rank'] > 30)
        current = {r['jid']: r for r in rows}
        top = rows[:50]
        relevant = [r for r in rows if r['rank'] <= 50 or (r['previous_rank'] and r['previous_rank'] <= 50)]
        movers = [r for r in relevant if r['rank_change'] is not None]
        total = sum(r['total'] for r in rows)
        stats = {'total': total, 'annual': sum(r['annual'] for r in rows), 'contacts': len(rows), 'active_contacts': sum(r['annual'] > 0 for r in rows), 'sent': sum(r['sent'] for r in rows), 'received': sum(r['received'] for r in rows), 'top50_share_pct': round(sum(r['total'] for r in top) / total * 100, 1) if total else 0,
                 'top_risers': sorted([r for r in movers if r['rank_change'] > 0], key=lambda r: (-r['rank_change'], r['rank']))[:5],
                 'top_fallers': sorted([r for r in movers if r['rank_change'] < 0], key=lambda r: (r['rank_change'], r['rank']))[:5],
                 'top_volume': sorted([r for r in rows if r['annual'] > 0], key=lambda r: (-r['annual'], r['jid']))[:5],
                 'top_growth': sorted([r for r in rows if r['annual_change'] > 0], key=lambda r: (-r['annual_change'], r['jid']))[:5],
                 'entrants': [r for r in top if r['entered_top50']],
                 'exits': [dict(old, current_rank=current.get(jid, {}).get('rank')) for jid, old in previous.items() if old['rank'] <= 50 and current.get(jid, {}).get('rank', 999999) > 50]}
        if year >= first_year:
            endpoint = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=TZ), latest)
            annual_top50 = [dict(r, annual_rank=i) for i, r in enumerate(sorted([r for r in rows if r['annual'] > 0], key=lambda r: (-r['annual'], r['jid'])), 1)][:50]
            stats['top30_share_pct'] = round(sum(r['total'] for r in rows[:30]) / total * 100, 1) if total else 0
            result[str(year)] = {'annual_top50': annual_top50, 'annual_top30': annual_top50[:30], 'as_of': endpoint.isoformat() if year >= first_individual.year else None, 'data_missing': year < first_individual.year, 'partial': year >= latest.year, 'top50': top, 'top30': top[:30], 'ranking': rows, 'stats': stats}
        previous = current
    quality['individual_chats'] = sum(c['individual'] for c in chats.values())
    quality['unmapped_lid_chats'] = sum(j.endswith('@lid') and canonical_jid(j) == j and j not in aliases for j, c in chats.items() if c['individual'])
    quality['merged_duplicate_name_groups'] = duplicate_name_groups
    quality['merged_duplicate_name_chats'] = len(inferred_aliases)
    monthly_series = [{'month': month, 'sent': values[0], 'received': values[1], 'total': sum(values)} for month, values in sorted(monthly.items())]
    series_years = list(range(first_year, last_year + 1))
    chat_series = []
    for jid, entry in per_chat.items():
        annual = [sum(entry['years'].get(y, (0, 0))) for y in series_years]
        if any(annual):
            chat_series.append({'jid': jid, 'name': entry['name'], 'annual': annual})
    chat_series.sort(key=lambda row: row['name'].casefold())
    return {'timezone': str(TZ), 'first_message': earliest.isoformat(), 'first_individual_message': first_individual.isoformat(), 'last_message': latest.isoformat(), 'generated_at': dt.datetime.now(TZ).isoformat(), 'quality': dict(quality), 'name_merge_aliases': inferred_aliases, 'name_merge_groups': name_merge_groups, 'monthly_messages': monthly_series, 'series_years': series_years, 'chat_series': chat_series, 'years': result}


def write_csv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def render_archive(chats, folder):
    (folder / 'txt').mkdir(parents=True, exist_ok=True)
    (folder / 'html').mkdir(parents=True, exist_ok=True)
    index = []
    for jid, chat in chats.items():
        stem = hashlib.sha256(jid.encode()).hexdigest()[:20]
        name = chat['name'] or jid
        lines, bubbles = [], []
        for m in sorted(chat['messages'].values(), key=lambda m: (m['timestamp'], str(m.get('key_id', '')))):
            when = dt.datetime.fromtimestamp(m['timestamp'], TZ).strftime('%d/%m/%Y, %H:%M:%S')
            who = 'Tu' if m.get('from_me') else (m.get('sender') or name)
            text = str(m.get('data') or m.get('caption') or '[Messaggio senza testo]')
            if m.get('safe') or m.get('media'):
                # Archive paths/markup as plain text: no untrusted HTML execution.
                text = str(m.get('caption') or m.get('data') or '[Allegato]')
            lines.append(f'[{when}] {who}: {text}')
            cls = 'me' if m.get('from_me') else 'them'
            bubbles.append(f'<article class="{cls}"><small>{html.escape(when)} · {html.escape(who)}</small><p>{html.escape(text)}</p></article>')
        (folder / 'txt' / f'{stem}.txt').write_text('\n'.join(lines), encoding='utf-8')
        page = '<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + html.escape(name) + '</title><style>body{background:#eff4f1;font:16px system-ui;max-width:900px;margin:30px auto;padding:20px}article{background:white;border-radius:12px;padding:12px;margin:12px 15% 12px 0}article.me{background:#d8f5de;margin:12px 0 12px 15%}p{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#53695d}</style><h1>' + html.escape(name) + '</h1><p>Archivio testuale locale. Gli allegati non disponibili sono indicati nel testo. Tutte le date: Europe/Madrid.</p>' + ''.join(bubbles) + '</html>'
        (folder / 'html' / f'{stem}.html').write_text(page, encoding='utf-8')
        index.append({'jid': jid, 'name': name, 'individual': chat['individual'], 'records': len(chat['messages']), 'html': f'html/{stem}.html', 'txt': f'txt/{stem}.txt'})
    save_json(folder / 'index.json', index)
    links = ''.join(f'<li>{html.escape(c["name"])} ({c["records"]:,}) — <a href="{c["html"]}">HTML</a> · <a href="{c["txt"]}">TXT</a></li>' for c in sorted(index, key=lambda c: c['name'].casefold()))
    (folder / 'index.html').write_text('<!doctype html><html lang="it"><meta charset="utf-8"><title>Archivio WhatsApp</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto}li{margin:12px}</style><h1>Tutte le conversazioni</h1><p>L’archivio include gruppi e chat individuali; la dashboard analizza solo le individuali.</p><ul>' + links + '</ul></html>', encoding='utf-8')


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', choices=['auto', 'desktop', 'backup', 'json'], default='auto')
    p.add_argument('--backup')
    p.add_argument('--json')
    p.add_argument('--first-year', type=int, default=2014)
    p.add_argument('--last-year', type=int, default=dt.datetime.now(TZ).year)
    p.add_argument('--open', action='store_true')
    p.add_argument('--provenance')
    p.add_argument('--aliases', default=str(ROOT / 'aliases.json'))
    p.add_argument('--archive-db', default=str(ROOT / 'data/archive.sqlite'))
    args = p.parse_args()
    if args.last_year < args.first_year or args.last_year > dt.datetime.now(TZ).year:
        p.error('Intervallo anni non valido o futuro.')
    run = ROOT / 'data/runs' / dt.datetime.now(TZ).strftime('%Y%m%d-%H%M%S-%f')
    run.mkdir(parents=True)
    mode, source_path, audit = extract(args, run)
    if args.provenance:
        supplied = json.loads(pathlib.Path(args.provenance).read_text())
        if not supplied.get('comparison_completed'):
            raise RuntimeError('Confronto iPhone/Mac non completato: classifiche sospese.')
        mode, source_path, audit = supplied['kind'], supplied['path'], supplied
    data = load_export(run / 'source.json')
    meta = {'kind': mode, 'path': source_path, 'exporter_version': '0.13.0', 'acquired_at': dt.datetime.now(TZ).isoformat(), 'json_sha256': hashlib.sha256((run / 'source.json').read_bytes()).hexdigest(), 'exported_chats': len(data), 'exported_records': sum(len(c['messages']) for c in data.values()), **audit}
    if 'database_records' in meta:
        meta['records_not_exported'] = meta['database_records'] - meta['exported_records']
    save_json(run / 'manifest.json', meta)
    merged, added = merge(data, pathlib.Path(args.archive_db), meta)
    aliases = json.loads(pathlib.Path(args.aliases).read_text(encoding='utf-8'))
    report = make_report(merged, args.first_year, args.last_year, aliases)
    report['source'] = {k: v for k, v in meta.items() if k != 'chat_metadata'}
    report['new_records_in_archive'] = added
    report['source_duplicate_records'] = meta['exported_records'] - sum(len({('key:' + str(m['key_id'])) if m.get('key_id') else 'record:' + str(k) for k, m in c['messages'].items()}) for c in data.values())
    report['archive_records'] = sum(len(c['messages']) for c in merged.values())
    dest = ROOT / 'report'
    dest.mkdir(exist_ok=True)
    archive = ROOT / 'archive'
    save_json(archive / 'chats.json', merged)
    render_archive(merged, archive)
    save_json(dest / 'statistiche.json', report)
    with (dest / 'nomi_unificati.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'canonical_jid', 'merged_jids', 'chat_count'])
        writer.writeheader()
        for group in report['name_merge_groups']:
            writer.writerow({**group, 'merged_jids': '; '.join(group['merged_jids'])})
    fields = ['year', 'as_of', 'annual_rank', 'rank', 'name', 'jid', 'total', 'sent', 'received', 'annual', 'annual_sent', 'annual_received', 'previous_rank', 'rank_change', 'entered_top50', 'annual_change', 'annual_growth_pct']
    for key, filename in [('top50', 'top50_2014-oggi.csv'), ('annual_top50', 'top50_solo_anno.csv'), ('ranking', 'classifiche_complete.csv')]:
        rows = [dict(row, year=year, as_of=item['as_of']) for year, item in report['years'].items() for row in item[key]]
        write_csv(dest / filename, rows, fields)
    template = (ROOT / 'dashboard.html').read_text(encoding='utf-8')
    payload = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (dest / 'dashboard.html').write_text(template.replace('__REPORT_DATA__', payload), encoding='utf-8')
    text = ['# Top 50 cumulative — chat individuali', f'Fonte: {mode}. Ultimo messaggio disponibile: {report["last_message"]}.', 'Totali inviati + ricevuti; gruppi, canali, stati ed eventi di sistema esclusi.']
    for year, item in report['years'].items():
        text += [f'\n## {year} — ' + (f'fino a {item["as_of"]}' if item['as_of'] else 'storico individuale non disponibile'), '| # | Conversazione | Totale | Nell’anno | Δ posizione |', '|---:|---|---:|---:|---:|']
        for row in item['top50']:
            name = row['name'].replace('|', '\\|').replace('\n', ' ')
            change = 'Nuova' if row['rank_change'] is None else f'{row["rank_change"]:+d}'
            text.append(f'| {row["rank"]} | {name} | {row["total"]:,} | {row["annual"]:,} | {change} |')
    (dest / 'top50_annuali.md').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps({'source': mode, 'archive_records': report['archive_records'], 'new_records': added, 'individual_chats': report['quality']['individual_chats'], 'dashboard': str(dest / 'dashboard.html')}, ensure_ascii=False, indent=2))
    if args.open and sys.platform == 'darwin':
        subprocess.run(['open', str(dest / 'dashboard.html')], check=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as e:
        print(f'ERRORE: {e}', file=sys.stderr)
        sys.exit(1)
