#!/usr/bin/env python3
"""Verify Finder backup, export iPhone, compare with Mac; only then analyze."""
import argparse, collections, datetime as dt, hashlib, json, os, pathlib, plistlib, sqlite3, subprocess, sys, time
import update as u

ROOT = pathlib.Path(__file__).resolve().parent
DB_ID = '7c7fba66680ef796b916b067077cc246adacf01d'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def plist(path):
    with path.open('rb') as f:
        return plistlib.load(f)


def latest_backup(explicit=None):
    if explicit:
        return pathlib.Path(explicit).expanduser().resolve()
    try:
        candidates = [p for p in u.FINDER.iterdir() if p.is_dir()]
    except PermissionError as e:
        raise RuntimeError('Accesso negato. Impostazioni di Sistema > Privacy e sicurezza > Accesso completo al disco: abilita Codex o Terminale e riapri l’app. Nessun tentativo di aggirare le protezioni.') from e
    except FileNotFoundError:
        candidates = []
    if not candidates:
        return None
    def date(p):
        try:
            value = plist(p / 'Info.plist').get('Last Backup Date')
            if isinstance(value, dt.datetime):
                return value.replace(tzinfo=dt.timezone.utc).timestamp()
        except (FileNotFoundError, plistlib.InvalidFileException):
            pass
        return p.stat().st_mtime
    return max(candidates, key=date)


def readiness(path):
    if not path:
        return False, 'Nessun backup locale Finder trovato.'
    for name in ('Status.plist', 'Info.plist', 'Manifest.plist', 'Manifest.db'):
        if not (path / name).is_file():
            return False, f'Backup non ancora pronto: manca {name}.'
    status = plist(path / 'Status.plist')
    if status.get('SnapshotState') != 'finished':
        return False, f'Backup non concluso: SnapshotState={status.get("SnapshotState")}.'
    if (path / 'Manifest.db').stat().st_size == 0:
        return False, 'Manifest.db vuoto.'
    return True, 'Snapshot Finder concluso.'


def validate(path):
    status, info, manifest = (plist(path / n) for n in ('Status.plist', 'Info.plist', 'Manifest.plist'))
    audit = {'backup_path': str(path), 'snapshot_state': status.get('SnapshotState'), 'backup_state': status.get('BackupState'), 'is_full_backup': status.get('IsFullBackup'), 'backup_date': str(info.get('Last Backup Date') or status.get('Date')), 'encrypted': manifest.get('IsEncrypted'), 'device_name': info.get('Device Name'), 'backup_completion_check': 'SnapshotState=finished; controllo manifest e payload ove leggibili', 'checked_at': dt.datetime.now(u.TZ).isoformat()}
    if audit['encrypted'] is None:
        raise RuntimeError('IsEncrypted assente dal manifest: verifica del backup necessaria.')
    audit['original_hashes'] = {n: sha(path / n) for n in ('Status.plist', 'Info.plist', 'Manifest.plist', 'Manifest.db')}
    if not audit['encrypted']:
        with sqlite3.connect((path / 'Manifest.db').as_uri() + '?mode=ro', uri=True) as c:
            integrity = c.execute('PRAGMA quick_check').fetchone()[0]
            if integrity != 'ok':
                raise RuntimeError('Manifest SQLite non integro: ' + str(integrity))
            audit['manifest_integrity'] = integrity
            count, missing = 0, []
            for (file_id,) in c.execute('SELECT fileID FROM Files WHERE flags=1'):
                count += 1
                if not (path / file_id[:2] / file_id).is_file() and not (path / file_id).is_file():
                    missing.append(file_id)
            audit['manifest_regular_files'] = count
            audit['missing_payload_count'] = len(missing)
            if missing:
                raise RuntimeError(f'Backup non completo: {len(missing)} file dichiarati nel manifest assenti. Non avvio l’esportazione.')
            wa = c.execute("SELECT fileID FROM Files WHERE relativePath='ChatStorage.sqlite' AND domain='AppDomainGroup-group.net.whatsapp.WhatsApp.shared'").fetchone()
            if not wa:
                raise RuntimeError('ChatStorage.sqlite di WhatsApp non incluso nel backup Finder. Non uso il Mac come sostituto.')
            audit['whatsapp_database_file_id'] = wa[0]
    return audit


def is_user_message(m):
    return m.get('message_type') != 6 and not (m.get('meta') and m.get('message_type') is None)


def summary(data):
    dates, users, user_dates, individual_dates = [], [], [], []
    annual = collections.Counter()
    chat_stats = {}
    for jid, chat in data.items():
        ms = list(chat['messages'].values())
        ts = [m['timestamp'] / 1000 if m['timestamp'] > 9999999999 else m['timestamp'] for m in ms]
        dates.extend(ts)
        real = [m for m in ms if is_user_message(m)]
        users.extend(real)
        real_times = [m['timestamp'] / (1000 if m['timestamp'] > 9999999999 else 1) for m in real]
        user_dates.extend(real_times)
        years = collections.Counter()
        for m in real:
            t = m['timestamp'] / 1000 if m['timestamp'] > 9999999999 else m['timestamp']
            year = dt.datetime.fromtimestamp(t, u.TZ).year
            years[year] += 1
            if jid.endswith(('@s.whatsapp.net', '@lid')):
                individual_dates.append(t)
                annual[year] += 1
        iso = lambda t: dt.datetime.fromtimestamp(t, u.TZ).isoformat() if t is not None else None
        chat_stats[jid] = {'name': chat.get('name'), 'records': len(ms), 'user_messages': len(real), 'min_date': iso(min(ts)) if ts else None, 'max_date': iso(max(ts)) if ts else None, 'min_user_date': iso(min(real_times)) if real_times else None, 'max_user_date': iso(max(real_times)) if real_times else None, 'annual_user_messages': dict(sorted(years.items()))}
    iso = lambda t: dt.datetime.fromtimestamp(t, u.TZ).isoformat() if t is not None else None
    return {'records': sum(len(c['messages']) for c in data.values()), 'user_messages': len(users), 'chats': len(data), 'chats_with_messages': sum(bool(c['messages']) for c in data.values()), 'individual_chats_with_messages': sum(bool(c['messages']) and j.endswith(('@s.whatsapp.net', '@lid')) for j,c in data.items()), 'min_date': iso(min(dates)) if dates else None, 'max_date': iso(max(dates)) if dates else None, 'first_user_message': iso(min(user_dates)) if user_dates else None, 'last_user_message': iso(max(user_dates)) if user_dates else None, 'first_individual_message': iso(min(individual_dates)) if individual_dates else None, 'annual_individual_messages': dict(sorted(annual.items())), 'per_chat': chat_stats}


def integrate(iphone, mac, aliases):
    # Primary = iPhone. Only verified chat aliases and stable stanza IDs match.
    combined = json.loads(json.dumps(iphone))
    seen = {}
    counters = collections.Counter()
    unresolved, conflicts = [], []
    canonical = lambda jid: aliases.get(jid, jid)
    iphone_chats = {}
    for jid, chat in combined.items():
        iphone_chats.setdefault(canonical(jid), jid)
        for m in chat['messages'].values():
            if m.get('key_id'):
                seen[(canonical(jid), str(m['key_id']))] = m
    for jid, chat in mac.items():
        target = iphone_chats.get(canonical(jid), jid)
        for record_id, m in chat['messages'].items():
            key = m.get('key_id')
            if not key:
                counters['mac_without_stable_id_not_integrated'] += 1
                unresolved.append({'jid': jid, 'record_id': record_id, 'reason': 'Identificativo stabile assente; nessuna deduplicazione certa.'})
                continue
            identity = (canonical(jid), str(key))
            if identity in seen:
                counters['overlapping_stable_records'] += 1
                left = seen[identity]
                # Preserve iPhone content on conflicts; keep original datasets for audit.
                check = lambda x: (round(x['timestamp'] / (1000 if x['timestamp'] > 9999999999 else 1), 3), bool(x.get('from_me')), x.get('message_type'), x.get('data') if not x.get('media') else x.get('caption'))
                if check(left) != check(m):
                    counters['conflicting_stable_records_iphone_kept'] += 1
                    conflicts.append({'iphone_jid': target, 'mac_jid': jid, 'key_id': str(key)})
                continue
            if target not in combined:
                combined[target] = {k:v for k,v in chat.items() if k!='messages'}
                combined[target]['messages'] = {}
            combined[target]['messages']['mac:' + str(key)] = m
            seen[identity] = m
            counters['mac_unique_stable_records_integrated'] += 1
    return combined, dict(counters), unresolved, conflicts


def compare(iphone, mac, folder, aliases):
    left, right = summary(iphone), summary(mac)
    combined, dedup, unresolved, conflicts = integrate(iphone, mac, aliases)
    report = {'iphone': {k:v for k,v in left.items() if k!='per_chat'}, 'mac': {k:v for k,v in right.items() if k!='per_chat'}, 'deduplication': dedup, 'verified_chat_aliases': aliases, 'selection': 'iPhone come fonte principale; aggiunti solo record Mac non sovrapposti con identificativo stabile. Identità senza mappatura certa restano distinte.', 'per_chat': {jid: {'iphone': left['per_chat'].get(jid), 'mac': right['per_chat'].get(jid)} for jid in sorted(set(left['per_chat']) | set(right['per_chat']))}}
    u.save_json(folder / 'confronto.json', report)
    u.save_json(folder / 'identita_da_verificare.json', unresolved)
    u.save_json(folder / 'conflitti_identificativi.json', conflicts)
    u.save_json(folder / 'dataset_integrato.json', combined)
    rows = []
    for jid, detail in report['per_chat'].items():
        a,b = detail['iphone'] or {}, detail['mac'] or {}
        rows.append({'jid':jid, 'canonical_jid':aliases.get(jid,jid), 'name':a.get('name') or b.get('name'), 'iphone_records':a.get('records',0), 'mac_records':b.get('records',0), 'iphone_min':a.get('min_user_date'), 'iphone_max':a.get('max_user_date'), 'mac_min':b.get('min_user_date'), 'mac_max':b.get('max_user_date'), 'iphone_years':json.dumps(a.get('annual_user_messages',{})), 'mac_years':json.dumps(b.get('annual_user_messages',{}))})
    u.write_csv(folder / 'copertura_per_chat.csv', rows, ['jid','canonical_jid','name','iphone_records','mac_records','iphone_min','iphone_max','mac_min','mac_max','iphone_years','mac_years'])
    u.save_json(folder / 'provenance.json', {'kind':'iphone+mac_stable', 'path':str(folder / 'dataset_integrato.json'), 'exporter_version':'0.13.0', 'iphone_export':str(folder / 'iphone.json'), 'comparison':str(folder / 'confronto.json'), 'comparison_completed':True, 'acquired_at':dt.datetime.now(u.TZ).isoformat()})
    return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup')
    parser.add_argument('--resume', help='Riprende il JSON/TXT da un run già estratto senza rigenerare l’HTML monolitico.')
    parser.add_argument('--wait', action='store_true', help='Attende il completamento di Finder; verifica ogni 30 secondi.')
    parser.add_argument('--analyze', action='store_true', help='Genera le classifiche solo dopo esportazione e confronto.')
    parser.add_argument('--mac-json', help='Esportazione Mac di riferimento; altrimenti usa l’ultima estrazione desktop.')
    args = parser.parse_args()
    while True:
        backup = latest_backup(args.backup)
        ready, reason = readiness(backup)
        if ready:
            break
        if not args.wait:
            raise RuntimeError(reason + ' Completa un backup Finder su questo Mac; nessun ripiego sul database Mac.')
        print(dt.datetime.now(u.TZ).strftime('%H:%M:%S'), reason, flush=True)
        time.sleep(30)
    audit = validate(backup)
    if args.resume:
        folder = pathlib.Path(args.resume).expanduser().resolve()
        try:
            folder.relative_to((ROOT / 'data/iphone-runs').resolve())
        except ValueError:
            raise RuntimeError('--resume deve puntare a una cartella data/iphone-runs di questo progetto.')
        audit_path = folder / 'backup-verificato.json'
        if not audit_path.is_file() or not (folder / DB_ID).is_file():
            raise RuntimeError('Run non completo o senza database estratto; riparti dal backup Finder.')
        audit = json.loads(audit_path.read_text())
        if audit.get('backup_path') != str(backup) or audit.get('snapshot_state') != 'finished':
            raise RuntimeError('Il run appartiene a un backup diverso o incompleto.')
        for name,expected in audit.get('original_hashes',{}).items():
            if sha(backup / name) != expected:
                raise RuntimeError(f'{name} è cambiato dal run precedente. Nessun output sovrascritto.')
        if not (folder / 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared').is_dir():
            raise RuntimeError('Media WhatsApp già estratti non trovati nel run.')
    else:
        folder = ROOT / 'data/iphone-runs' / dt.datetime.now(u.TZ).strftime('%Y%m%d-%H%M%S-%f')
        folder.mkdir(parents=True)
        u.save_json(folder / 'backup-verificato.json', audit)
    if audit['encrypted']:
        subprocess.run([str(ROOT / '.venv/bin/python'),'-m','pip','install','git+https://github.com/KnugiHK/iphone_backup_decrypt@190d61c849045aded1863aa4bd1466e4d265f53d'],check=True)
        print('Inserisci la password del backup esclusivamente nel prompt del Terminale.')
    cmd = [u.exporter(), '-i', '-b', str(backup), '-o', str(folder / 'html'), '-j', str(folder / 'iphone.json'), '--txt', str(folder / 'txt'), '--no-html', '--no-banner']
    print('Avvio WhatsApp Chat Exporter sul backup iPhone:', str(backup), flush=True)
    subprocess.run(cmd, cwd=folder, check=True)
    for name, expected in audit['original_hashes'].items():
        if sha(backup / name) != expected:
            raise RuntimeError(f'{name} è cambiato durante l’estrazione. Non genero le classifiche; il backup potrebbe essere ancora in scrittura.')
    iphone = u.load_export(folder / 'iphone.json')
    db = folder / DB_ID
    if db.exists():
        with sqlite3.connect(db.as_uri() + '?mode=ro',uri=True) as c:
            if c.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database WhatsApp estratto non integro.')
            audit['whatsapp_database_records'] = c.execute('SELECT count(*) FROM ZWAMESSAGE').fetchone()[0]
    html_dir = folder / 'html-complete'
    html_dir.mkdir(exist_ok=True)
    html_cmd = [str(ROOT / '.venv/bin/wtsexporter'), '--import', '--json', str(folder / 'iphone.json'), '--output', str(html_dir), '--size', '16MB', '--no-avatar', '--no-banner']
    print('Genero le pagine HTML a blocchi da 16 MB, evitando singoli file di centinaia di MB.', flush=True)
    subprocess.run(html_cmd, cwd=folder, check=True)
    audit['html_pages'] = sum(1 for f in html_dir.glob('*.html'))
    audit['exported_records'] = sum(len(c['messages']) for c in iphone.values())
    audit['original_manifest_unchanged'] = True
    html_files = sorted(html_dir.glob('*.html'))
    (html_dir / 'README.html').write_text('<!doctype html><meta charset="utf-8"><title>Export WhatsApp iPhone</title><h1>Conversazioni esportate</h1><p>Le chat più lunghe sono suddivise in pagine.</p><ul>' + ''.join('<li><a href="' + f.name.replace('&','&amp;').replace('<','&lt;').replace('\"','&quot;') + '">' + f.stem.replace('&','&amp;').replace('<','&lt;') + '</a></li>' for f in html_files if f.name != 'README.html') + '</ul>', encoding='utf-8')
    u.save_json(folder / 'backup-verificato.json', audit)
    if args.mac_json:
        mac_path = pathlib.Path(args.mac_json).expanduser().resolve()
    else:
        candidates = []
        for manifest in (ROOT / 'data/runs').glob('*/manifest.json'):
            meta = json.loads(manifest.read_text())
            if meta.get('kind') == 'desktop':
                candidates.append(manifest.parent / 'source.json')
        if not candidates:
            raise RuntimeError('JSON Mac di confronto assente: specifica --mac-json. iPhone esportato, classifiche sospese.')
        mac_path = max(candidates,key=lambda p:p.stat().st_mtime)
    aliases = json.loads((ROOT / 'aliases.json').read_text())
    lid_db = folder / 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared/LID.sqlite'
    if lid_db.exists():
        with sqlite3.connect(lid_db.as_uri() + '?mode=ro', uri=True) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='ZWAPHONENUMBERLIDPAIR'").fetchone():
                for lid, number in c.execute('SELECT ZLID,ZPHONENUMBER FROM ZWAPHONENUMBERLIDPAIR'):
                    if lid and number:
                        lid = str(lid) if '@' in str(lid) else str(lid) + '@lid'
                        number = str(number) if '@' in str(number) else str(number).lstrip('+') + '@s.whatsapp.net'
                        aliases.setdefault(lid, number)
    u.save_json(folder / 'aliases-verificati.json', aliases)
    report = compare(iphone,u.load_export(mac_path),folder,aliases)
    u.save_json(ROOT / 'data/latest-iphone.json', {'folder':str(folder), 'backup':str(backup), 'comparison_completed':True})
    print(json.dumps({k:v for k,v in report.items() if k!='per_chat'},ensure_ascii=False,indent=2))
    print('Confronto:',folder / 'confronto.json')
    if args.analyze:
        subprocess.run([str(ROOT / '.venv/bin/python'),str(ROOT / 'update.py'),'--source','json','--json',str(folder / 'dataset_integrato.json'),'--provenance',str(folder / 'provenance.json'),'--aliases',str(folder / 'aliases-verificati.json'),'--archive-db',str(ROOT / 'data/iphone_archive.sqlite'),'--open'],check=True)
    else:
        print('Classifiche sospese: verifica il confronto, poi riesegui con --analyze.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError,ValueError,OSError,subprocess.CalledProcessError) as e:
        print('ERRORE:',e,file=sys.stderr)
        sys.exit(1)
