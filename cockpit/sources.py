"""Read existing records without executing any operational command."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import yaml

from .actions import revision


def stamp():
    return datetime.now(timezone.utc).isoformat()


def read_document(path):
    path = Path(path)
    if path.stat().st_size > 12_000_000:
        raise ValueError('Source exceeds the bounded reader')
    value = yaml.safe_load(path.read_text()) if path.suffix in ('.yaml', '.yml') else json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Source is not an object')
    return value


def safe_url(value):
    return value if isinstance(value, str) and value.startswith(('https://', 'http://')) else ''


def source_record(name, path, status, detail=''):
    try: updated = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()
    except OSError: updated = None
    return {'name': name, 'status': status, 'updated_at': updated, 'observed_at': stamp(), 'detail': detail}


def local_work(config):
    path = config['BACKLOG_PATH']
    try:
        data = read_document(path)
        rows = data['items']
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Invalid queue')
        counts = Counter(row.get('id') for row in rows)
        work = []
        for row in rows:
            if row.get('status') not in ('open', 'held', 'in_review'):
                continue
            iid = str(row.get('id', ''))
            work.append({'id': iid, 'title': str(row.get('title') or 'Untitled work'),
                         'repo': str(row.get('repo') or 'Unassigned'), 'status': row['status'],
                         'why': str(row.get('note') or 'No decision reason recorded.'),
                         'created': str(row.get('created') or ''), 'source': 'Shared backlog',
                         'source_url': safe_url(row.get('source')), 'revision': revision(row),
                         'can_hold': bool(iid) and counts[iid] == 1 and row['status'] in ('open', 'in_review')})
        return work, source_record('Shared backlog', path, 'available', 'All active items, including held work.')
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return [], source_record('Shared backlog', path, 'unavailable', 'The queue could not be read. An empty view does not mean no work.')


def health_sources(config, catalog):
    out = []
    root = Path(config['PROJECTS_ROOT'])
    for check in catalog.get('checks', []):
        path = Path(check['path'].replace('{projects}', str(root)).replace('{home}', str(Path.home())))
        try:
            data = read_document(path)
            seen = data.get(check.get('time_field', 'checked_at'))
            observed = datetime.fromisoformat(str(seen).replace('Z', '+00:00'))
            if observed.tzinfo is None: raise ValueError('Timestamp lacks timezone')
            age = (datetime.now(timezone.utc) - observed).total_seconds()
            status = 'current' if 0 <= age <= check['max_age_seconds'] else 'overdue'
            if age < 0: status = 'unavailable'
            if data.get('status') in ('error', 'failed'): status = 'failed'
            out.append({'name': check['name'], 'status': status, 'updated_at': observed.isoformat(),
                        'observed_at': stamp(), 'detail': check['meaning']})
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            out.append(source_record(check['name'], path, 'unavailable', check['meaning']))
    if not out:
        out.append({'name': 'Unattended work', 'status': 'unavailable', 'updated_at': None,
                    'observed_at': stamp(), 'detail': 'No expected-result feeds are configured.'})
    return out


def resources(config):
    path = Path(config.get('USAGE_DB') or Path.home() / '.local/state/venice-usage/ledger.db')
    result = {'cash_result': None, 'cash_spend': None, 'allocation': None, 'owner_time_eur_per_hour': 75,
              'time_value_is_nominal': True, 'usage': [], 'observed_at': stamp(),
              'detail': 'Cash results and allocations are not reconciled. Tokens measure recorded use, not cash or value.'}
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            # Match the existing ledger schema, verified at this source boundary.
            rows = db.execute('SELECT project, COUNT(*) AS calls, SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out FROM usage WHERE ts >= ? GROUP BY project ORDER BY SUM(tokens_in) DESC', (since,)).fetchall()
        result.update(usage=[dict(row) for row in rows], since=since, status='available')
    except (OSError, sqlite3.Error):
        result['status'] = 'unavailable'
    return result


def snapshot(config):
    try:
        catalog = read_document(config['CATALOG_PATH'])
        catalog_source = source_record('Portfolio direction and decisions', config['CATALOG_PATH'], 'available', 'Accepted direction and dated audit evidence; proposals stay proposals.')
    except (OSError, ValueError, yaml.YAMLError):
        catalog = {}
        catalog_source = source_record('Portfolio direction and decisions', config['CATALOG_PATH'], 'unavailable', 'Direction could not be read.')
    work, backlog_source = local_work(config)
    sources = [catalog_source, backlog_source, *health_sources(config, catalog)]
    if config.get('REMOTE_READS'):
        from .remote import remote_work
        remote, remote_sources = remote_work(config)
        # An Ops row may point to the same backlog item. Keep its owner source link.
        existing = {row['id']: row for row in work}
        for row in remote:
            linked = row.pop('backlog_id', None)
            if linked in existing:
                existing[linked]['source_url'] = row['source_url']
                existing[linked]['owner_surface_status'] = row['status']
            else:
                work.append(row)
        sources.extend(remote_sources)
    else:
        sources.append({'name': 'Notion owner queues', 'status': 'unavailable', 'updated_at': None,
                        'observed_at': stamp(), 'detail': 'Remote reads are not enabled in this view.'})
    known_repos = {repo for initiative in catalog.get('initiatives', []) for repo in initiative.get('repos', [])}
    coverage = sorted({row['repo'] for row in work if row['repo'] not in known_repos})
    return {'generated_at': stamp(), 'initiatives': catalog.get('initiatives', []),
            'decisions': catalog.get('decisions', []), 'work': work, 'sources': sources,
            'resources': resources(config), 'unmapped_repositories': coverage,
            'coverage_notes': catalog.get('coverage_notes', []), 'mode': 'Decision controls enabled' if config.get('ENABLE_ACTIONS') else 'Read-only view'}
