"""Browser acceptance check with demo access protection enabled.

Requires a built frontend and Chromium. Runs isolated synthetic services with explicit
per-run test credentials and keeps screenshots under the requested folder.
Usage: python backend/scripts/verify_review_workflow.py [artifact-directory]
"""
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

from harness_api import SameSiteApi, sign_in
from verify_access_protection import (verify_before_sign_in, verify_exports_protected_after_workflow,
                                      verify_no_secret_exposure, verify_restore_invalidates_sessions,
                                      verify_sign_out_failures, verify_with_session)
from verify_client_report import verify_client_report
from verify_households import verify_households

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.security import hash_password  # noqa: E402
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/advisorlens-browser-evidence')
OUT.mkdir(parents=True, exist_ok=True)
processes = []


def ready(url):
    for _ in range(40):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.5)
    raise RuntimeError(f'Service did not start: {url}')


class Backend:
    """The API process, which the access checks stop and restart (unavailable backend,
    restore from backup) against the same database and credentials."""

    def __init__(self, env, log):
        self.env, self.log, self.process = env, log, None
        self.db_path = Path(env['ADVISORLENS_DB'])

    def start(self):
        self.process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
                                        cwd=ROOT/'backend', env=self.env, stdout=self.log, stderr=self.log)
        ready('http://127.0.0.1:8000/health')

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None


with tempfile.TemporaryDirectory() as temporary:
    log = open(OUT / 'services.log', 'w')
    try:
        # Explicit test credentials, random per run; never a fallback to an unprotected mode.
        creds = {'password': 'harness-demo-password',
                 'backend_secret': 'harness-backend-' + secrets.token_urlsafe(24),
                 'session_secret': 'harness-session-' + secrets.token_urlsafe(24)}
        env = {**{k: v for k, v in os.environ.items() if not k.startswith('ADVISORLENS_')},
               'ADVISORLENS_ENV': 'test',
               'ADVISORLENS_DB': str(Path(temporary) / 'demo.db'),
               'ADVISORLENS_BRIEF_GENERATOR': 'deterministic-v1',
               'ADVISORLENS_BACKEND_SECRET': creds['backend_secret'],
               'ADVISORLENS_DEMO_PASSWORD_HASH': hash_password(creds['password']),
               'ADVISORLENS_SESSION_SECRET': creds['session_secret'],
               'ADVISORLENS_BACKEND_URL': 'http://127.0.0.1:8000',
               'ADVISORLENS_PUBLIC_ORIGIN': 'http://127.0.0.1:3100',
               'ADVISORLENS_TRUST_PROXY_HEADERS': 'true'}
        if os.environ.get('ADVISORLENS_CHROMIUM_PATH'):
            env['ADVISORLENS_CHROMIUM_PATH'] = os.environ['ADVISORLENS_CHROMIUM_PATH']
        backend = Backend(env, log)
        backend.start()
        processes.append(subprocess.Popen(['npm', 'run', 'start', '--', '--hostname', '127.0.0.1', '--port', '3100'], cwd=ROOT/'frontend', env=env, stdout=log, stderr=log, start_new_session=True))
        ready('http://127.0.0.1:3100/login')
        with sync_playwright() as p:
            launch = {'executable_path': os.environ['ADVISORLENS_CHROMIUM_PATH']} if os.environ.get('ADVISORLENS_CHROMIUM_PATH') else {}
            browser = p.chromium.launch(**launch)
            access_checks = verify_before_sign_in(browser, OUT, creds)
            page = browser.new_context(viewport={'width':1440, 'height':1000}).new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            sign_in(page, creds['password'])
            access_checks += verify_with_session(browser, page, OUT, creds)
            access_checks += verify_sign_out_failures(browser, OUT, creds, backend)
            api = SameSiteApi(page)
            page.goto('http://127.0.0.1:3100/workspace')
            page.get_by_role('button', name='growth concentrated', exact=True).click()
            card = page.get_by_role('article').first
            expect(card.get_by_label('Review status')).to_have_value('open')
            card.get_by_label('Review status').select_option('follow_up')
            card.get_by_label('Advisor note', exact=True).fill('Confirm liquidity needs at the next meeting.')
            card.get_by_role('button', name='Save review', exact=True).click()
            expect(card.get_by_role('status')).to_have_text('Review saved.')
            page.reload()
            page.get_by_role('button', name='history', exact=True).click()
            page.get_by_role('button', name='Open', exact=True).first.click()
            card = page.get_by_role('article').first
            expect(card.get_by_label('Review status')).to_have_value('follow_up')
            expect(card.get_by_label('Advisor note', exact=True)).to_have_value('Confirm liquidity needs at the next meeting.')
            card.get_by_label('Review status').select_option('resolved')
            card.get_by_label('Advisor note', exact=True).fill('')
            expect(card.get_by_role('button', name='Save review', exact=True)).to_be_disabled()
            card.get_by_label('Advisor note', exact=True).fill('Discussed concentration and documented the decision.')
            card.get_by_role('button', name='Save review', exact=True).click()
            expect(card.get_by_role('status')).to_have_text('Review saved.')
            card.get_by_text('Decision history (2)', exact=True).click()
            expect(card.get_by_text('Confirm liquidity needs at the next meeting.', exact=True)).to_be_visible()
            page.screenshot(path=str(OUT/'queue-desktop.png'), full_page=True)

            # A concurrent API update must cause a visible conflict, not lost notes.
            aid = api.get('/analyses').json()['analyses'][0]['id']
            item = api.get(f'/analyses/{aid}/reviews').json()['items'][0]
            endpoint = f"/analyses/{aid}/reviews/{item['finding_id']}"
            assert api.put(endpoint, data={'status':'discussed','note':'Saved from another tab.','expected_version':item['version']}).status == 200
            card.get_by_label('Advisor note', exact=True).fill('Stale local draft.')
            card.get_by_role('button', name='Save review', exact=True).click()
            expect(card.get_by_role('alert')).to_contain_text('updated elsewhere')
            expect(card.get_by_label('Advisor note', exact=True)).to_have_value('Stale local draft.')
            card.get_by_role('button', name='Discard draft and load latest review').click()
            expect(card.get_by_label('Advisor note', exact=True)).to_have_value('Saved from another tab.')
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(OUT/'queue-mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile page overflows'
            assert not errors, errors
            # Existing print endpoint must still yield an actual PDF.
            pdf = api.get(f'/analyses/{aid}/brief/pdf')
            assert pdf.status == 200 and pdf.body().startswith(b'%PDF')
            (OUT/'result.json').write_text(json.dumps({'status':'passed','checks':['save','reload','resolve-note-required','history','stale-update-conflict','mobile-overflow','no-page-errors','pdf-export']}))
            for name, check in [('household', verify_households), ('report', verify_client_report)]:
                try:
                    check(page, OUT)
                except Exception:
                    page.screenshot(path=str(OUT/f'{name}-failure.png'), full_page=True)
                    (OUT/f'{name}-failure.html').write_text(page.content())
                    (OUT/'page-errors.json').write_text(json.dumps(errors))
                    raise
            assert not errors, errors
            access_checks += verify_exports_protected_after_workflow(browser)
            scan_checks, scanned_urls, scanned_files = verify_no_secret_exposure(browser, page, creds)
            access_checks += scan_checks
            # Last: a restore invalidates every session, including the one used above.
            access_checks += verify_restore_invalidates_sessions(browser, page, OUT, creds, backend, Path(temporary))
            (OUT/'access-result.json').write_text(json.dumps({'status': 'passed', 'checks': access_checks,
                'scanned_response_urls': scanned_urls, 'scanned_static_files': scanned_files}))
            browser.close()
    finally:
        if 'backend' in globals():
            backend.stop()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        log.close()
