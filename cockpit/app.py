"""Private owner cockpit. No operational action runs on a read request."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import os
from pathlib import Path
import secrets
import time

from flask import Flask, abort, jsonify, redirect, render_template, request, session
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash
from werkzeug.exceptions import SecurityError

from . import actions, sources


def create_app(config=None):
    app = Flask(__name__)
    projects = Path(os.environ.get('COCKPIT_PROJECTS', str(Path.home() / 'projects')))
    app.config.update(
        SECRET_KEY=os.environ.get('COCKPIT_SECRET_KEY', ''), PASSWORD_HASH=os.environ.get('COCKPIT_PASSWORD_HASH', ''),
        SESSION_COOKIE_NAME='portfolio_session', SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict', PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
        MAX_CONTENT_LENGTH=16_384, MAX_FORM_PARTS=8,
        TRUSTED_HOSTS=os.environ.get('COCKPIT_HOSTS', 'localhost,127.0.0.1').split(','),
        PROJECTS_ROOT=str(projects), BACKLOG_PATH=str(projects / 'backlog/backlog.yaml'),
        STATE_ROOT=str(projects / '.backlog-run'), CATALOG_PATH=str(Path(__file__).with_name('portfolio.json')),
        REMOTE_READS=os.environ.get('COCKPIT_REMOTE_READS') == '1',
        ENABLE_ACTIONS=os.environ.get('COCKPIT_ENABLE_ACTIONS') == '1',
        DOCS_ROOT=os.environ.get('COCKPIT_DOCS_ROOT', str(Path(__file__).resolve().parent.parent / 'docs')),
        PUBLIC_ORIGIN=os.environ.get('COCKPIT_PUBLIC_ORIGIN', ''),
    )
    app.config.update(config or {})
    if len(app.config['SECRET_KEY']) < 32 or not app.config['PASSWORD_HASH']:
        raise ValueError('Set a strong cockpit signing key and owner password hash before starting')
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='portfolio-owner-action')
    attempts = {}

    @app.before_request
    def protect():
        if isinstance(request.routing_exception, SecurityError):
            raise request.routing_exception
        if request.method == 'POST':
            expected_origin = app.config['PUBLIC_ORIGIN'] or request.host_url.rstrip('/')
            if request.headers.get('Origin') and request.headers['Origin'] != expected_origin:
                abort(403)
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf', '')
            if not supplied or not session.get('csrf') or not secrets.compare_digest(supplied, session['csrf']):
                abort(403)
        if request.endpoint not in ('login', 'static') and not session.get('owner'):
            if request.path.startswith('/api/'):
                return jsonify(error='Log in to see your portfolio.'), 401
            return redirect('/login')

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY', 'Referrer-Policy': 'same-origin',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = ''
        if request.method == 'POST':
            key, now = request.remote_addr or 'owner', time.monotonic()
            tries, start = attempts.get(key, (0, now))
            if now - start >= 60: tries, start = 0, now
            if tries >= 5: return render_template('login.html', error='Wait one minute, then try again.', csrf=session['csrf']), 429
            attempts[key] = (tries + 1, start)
            if check_password_hash(app.config['PASSWORD_HASH'], request.form.get('password', '')):
                attempts.pop(key, None)
                session.clear()
                session.update(owner=True, csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect('/')
            error = 'That password did not match.'
        if 'csrf' not in session: session['csrf'] = secrets.token_urlsafe(32)
        return render_template('login.html', error=error, csrf=session['csrf'])

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.get('/')
    def index():
        return render_template('index.html', csrf=session['csrf'])

    @app.get('/api/snapshot')
    def snapshot():
        data = sources.snapshot(app.config)
        for item in data['work']:
            if item.pop('can_hold', False) and app.config['ENABLE_ACTIONS']:
                item['hold_token'] = signer.dumps({'id': item['id'], 'revision': item['revision'], 'action': 'hold'})
            item.pop('revision', None)
        return jsonify(data)

    @app.post('/api/work/<item_id>/hold')
    def hold(item_id):
        if not app.config['ENABLE_ACTIONS']: abort(403)
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(error='Provide the current decision and a short reason.'), 400
        token, reason = body.get('token'), body.get('reason')
        if not isinstance(token, str) or not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
            return jsonify(error='Provide the current decision and a short reason.'), 400
        try:
            claim = signer.loads(token, max_age=3600)
            if claim.get('id') != item_id or claim.get('action') != 'hold': raise BadSignature('Wrong action')
            decision_id = hashlib.sha256((token + '\0' + reason.strip()).encode()).hexdigest()
            result = actions.hold(app.config, item_id, claim['revision'], reason.strip(), decision_id)
            return jsonify(result)
        except BadSignature:
            return jsonify(error='This decision expired or changed. Refresh the view.'), 409
        except (actions.StaleDecision, KeyError, ValueError):
            return jsonify(error='The work changed. Refresh and review its current state.'), 409
        except (TimeoutError, SystemExit):
            return jsonify(error='The runner is using this queue. Nothing changed; try again after it finishes.'), 409
        except OSError:
            return jsonify(error='The queue write could not be confirmed. Refresh before trying again.'), 503

    @app.get('/decisions/<name>')
    def decision(name):
        # Only prepared decision documents are served, never a caller-supplied file path.
        if not name.endswith('.md') or '/' in name or '\\' in name: abort(404)
        root = Path(app.config['DOCS_ROOT']) / 'decisions'
        path = root / name
        if path.parent.resolve() != root.resolve() or not path.is_file() or path.is_symlink(): abort(404)
        return render_template('decision.html', title=name.replace('.md', '').replace('-', ' '), text=path.read_text())

    return app
