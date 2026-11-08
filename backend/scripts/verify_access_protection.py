"""Browser acceptance checks for demo access protection.

Called by verify_review_workflow.py, which starts both services with explicit
per-run test credentials (ADVISORLENS_ENV=test).
"""
import json
import re
import subprocess
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect

from harness_api import API, APP_ORIGIN, BACKEND, COOKIE_NAME, SameSiteApi, sign_in

ROOT = Path(__file__).resolve().parents[2]
ATTACKER_ORIGIN = 'http://127.0.0.1:3999'
PROTECTED_API = ['/analyses', '/households', '/samples', '/generator', '/analyses/1/brief/pdf',
                 '/reports/1/pdf', '/analyses/1/reports', '/auth/session']


def _seal(data: dict, secret: str) -> str:
    """Seal a session cookie with iron-session itself, to craft expired or forged sessions."""
    code = ("import {sealData} from 'iron-session';"
            "console.log(await sealData(JSON.parse(process.env.SEAL_DATA), {password: process.env.SEAL_SECRET, ttl: 8 * 3600}));")
    result = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT / 'frontend', check=True,
                            capture_output=True, text=True, env={'PATH': __import__('os').environ['PATH'],
                                                                 'SEAL_DATA': json.dumps(data), 'SEAL_SECRET': secret})
    return result.stdout.strip()


def _context_with_cookie(browser, value):
    context = browser.new_context()
    context.add_cookies([{'name': COOKIE_NAME, 'value': value, 'url': APP_ORIGIN}])
    return context


def _assert_signed_out(context, label):
    page = context.new_page()
    page.goto(f'{APP_ORIGIN}/workspace')
    expect(page).to_have_url(f'{APP_ORIGIN}/login?next=%2Fworkspace')
    for path in ['/analyses', '/reports/1/pdf']:
        r = context.request.get(API + path)
        assert r.status == 401, (label, path, r.status)
    context.close()


def verify_before_sign_in(browser, out, creds):
    checks = []
    context = browser.new_context()
    page = context.new_page()
    for path in ['/workspace', '/households']:
        page.goto(APP_ORIGIN + path)
        expect(page).to_have_url(f"{APP_ORIGIN}/login?next={path.replace('/', '%2F')}")
    checks.append('unauthenticated-pages-redirect-to-sign-in')
    page.screenshot(path=str(out / 'access-login.png'))
    for path in PROTECTED_API:
        r = context.request.get(API + path)
        assert r.status == 401, (path, r.status)
        assert 'no-store' in r.headers.get('cache-control', ''), path
    r = context.request.post(f'{API}/analyze/sample/growth_concentrated.csv', headers={'Origin': APP_ORIGIN})
    assert r.status == 401
    checks.append('proxy-rejects-unauthenticated-requests')

    backend = context.request
    assert backend.get(f'{BACKEND}/health').json() == {'status': 'ok'}
    for path in ['/analyses', '/households', '/reports/1/pdf', '/analyses/1/brief/pdf', '/docs', '/openapi.json']:
        assert backend.get(BACKEND + path).status == 401, path
        assert backend.get(BACKEND + path, headers={'x-advisorlens-backend-secret': 'wrong-' + creds['backend_secret']}).status == 401
    assert backend.post(f'{BACKEND}/auth/login', data={'password': creds['password'], 'client': 'x'}).status == 401
    checks.append('direct-backend-requests-without-secret-rejected')

    # Cross-origin sign-in attempts are refused before the password is checked.
    r = context.request.post(f'{API}/auth/login', data={'password': creds['password']},
                             headers={'Origin': ATTACKER_ORIGIN})
    assert r.status == 403
    # Repeated failures from one client are throttled; a correct password is then refused too.
    attacker = {'Origin': APP_ORIGIN, 'X-Forwarded-For': '203.0.113.50'}
    for _ in range(5):
        assert context.request.post(f'{API}/auth/login', data={'password': 'wrong'}, headers=attacker).status == 401
    blocked = context.request.post(f'{API}/auth/login', data={'password': creds['password']}, headers=attacker)
    assert blocked.status == 429 and int(blocked.headers['retry-after']) > 0
    assert 'Too many failed sign-in attempts' in blocked.json()['detail']
    checks.append('repeated-failed-logins-throttled')

    page.goto(f'{APP_ORIGIN}/login?next=%2Fworkspace')
    page.get_by_label('Demo password', exact=True).fill('not-the-password')
    page.get_by_role('button', name='Sign in', exact=True).click()
    expect(page.locator('form').get_by_role('alert')).to_have_text('Incorrect password.')
    page.screenshot(path=str(out / 'access-login-failed.png'))
    checks.append('wrong-password-message')
    context.close()
    return checks


def _start_attacker_site(directory: Path):
    (directory / 'attack.html').write_text(f'''<!doctype html><html><body>
<form id="f" method="POST" action="{APP_ORIGIN}/api/analyze/sample/growth_concentrated.csv"></form>
<script>
fetch("{APP_ORIGIN}/api/analyze/sample/retiree_cash_drag.csv", {{method: "POST", credentials: "include", mode: "no-cors"}})
  .finally(() => document.getElementById("f").submit());
</script></body></html>''')
    server = ThreadingHTTPServer(('127.0.0.1', 3999), partial(_QuietHandler, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def verify_with_session(browser, page, out, creds):
    """`page` is signed in. Checks CSRF/origin handling, cookies and session states."""
    checks = []
    api = SameSiteApi(page)
    cookie = next(c for c in page.context.cookies() if c['name'] == COOKIE_NAME)
    assert cookie['httpOnly'] and cookie['sameSite'] == 'Lax' and cookie['path'] == '/'
    assert COOKIE_NAME not in page.evaluate('document.cookie')
    checks.append('session-cookie-httponly-samesite-lax')

    before = len(api.get('/analyses').json()['analyses'])
    with tempfile.TemporaryDirectory() as site:
        server = _start_attacker_site(Path(site))
        try:
            attack = page.context.new_page()  # Same browser profile: the session cookie is present.
            with attack.expect_navigation(url=f'{APP_ORIGIN}/api/analyze/sample/growth_concentrated.csv') as nav:
                attack.goto(f'{ATTACKER_ORIGIN}/attack.html')
            assert nav.value.status == 403, nav.value.status
            expect(attack.locator('body')).to_contain_text('Cross-origin request refused.')
            attack.wait_for_timeout(500)
            attack.close()
        finally:
            server.shutdown()
    assert len(api.get('/analyses').json()['analyses']) == before, 'Cross-origin request created an analysis'
    checks.append('cross-origin-form-and-fetch-mutations-refused')

    token = page.request.get(f'{API}/auth/session').json()['csrfToken']
    for headers in [{'Origin': APP_ORIGIN}, {'Origin': APP_ORIGIN, 'X-CSRF-Token': 'forged'},
                    {'Origin': ATTACKER_ORIGIN, 'X-CSRF-Token': token}, {'X-CSRF-Token': token}]:
        r = page.request.post(f'{API}/analyze/sample/growth_concentrated.csv', headers=headers)
        assert r.status == 403, (headers, r.status)
    assert len(api.get('/analyses').json()['analyses']) == before
    r = api.get('/analyses')
    assert 'no-store' in r.headers['cache-control'] and 'private' in r.headers['cache-control']
    checks.append('csrf-token-and-origin-required')

    _assert_signed_out(_context_with_cookie(browser, cookie['value'][:-6] + 'AAAAAA'), 'tampered')
    now = int(time.time() * 1000)
    expired = _seal({'sid': 'expired-session-0123456789', 'csrf': 'x' * 43, 'iat': now - 9 * 3600_000,
                     'exp': now - 3600_000}, creds['session_secret'])
    _assert_signed_out(_context_with_cookie(browser, expired), 'expired')
    forged = _seal({'sid': 'forged-session-0123456789', 'csrf': 'x' * 43, 'iat': now, 'exp': now + 3600_000},
                   'forged-secret-' + creds['session_secret'])
    _assert_signed_out(_context_with_cookie(browser, forged), 'forged')
    checks.append('tampered-expired-forged-sessions-rejected')

    # Sign out in a second browser profile, then replay its copied cookie.
    other = browser.new_context()
    other_page = other.new_page()
    sign_in(other_page, creds['password'])
    copied = next(c['value'] for c in other.cookies() if c['name'] == COOKIE_NAME)
    other_page.get_by_role('button', name='Sign out', exact=True).click()
    expect(other_page).to_have_url(f'{APP_ORIGIN}/login?signedOut=1')
    expect(other_page.get_by_role('status')).to_have_text('You have been signed out.')
    assert not [c for c in other.cookies() if c['name'] == COOKIE_NAME]
    other_page.screenshot(path=str(out / 'access-signed-out.png'))
    other.close()
    _assert_signed_out(_context_with_cookie(browser, copied), 'signed-out')
    assert api.get('/analyses').status == 200  # The first session is unaffected.
    checks.append('signed-out-session-revoked-server-side')
    return checks


def _scan(text: bytes, secrets: list[str], where: str, found: list[str]):
    for secret in secrets:
        if secret.encode() in text:
            found.append(where)


def verify_no_secret_exposure(browser, page, creds):
    """Secrets must not appear in any browser-visible response or in the static bundle."""
    secrets = [creds['backend_secret'], creds['session_secret']]
    found: list[str] = []
    urls = set()
    page.on('response', lambda r: urls.add(r.url) if r.url.startswith(APP_ORIGIN) else None)
    for path in ['/', '/workspace', '/households']:
        page.goto(APP_ORIGIN + path)
        page.wait_for_load_state('networkidle')
    for path in ['/workspace', '/households', '/login']:
        r = page.request.get(APP_ORIGIN + path, headers={'RSC': '1'})
        _scan(r.body(), secrets, f'RSC {path}', found)
    for url in sorted(urls) + [API + p for p in ['/auth/session', '/generator', '/analyses', '/samples', '/reports/1']]:
        r = page.request.get(url)
        _scan(r.body() + json.dumps(r.headers).encode(), secrets, url, found)
    static = list((ROOT / 'frontend' / '.next' / 'static').rglob('*'))
    for path in static:
        if path.is_file():
            _scan(path.read_bytes(), secrets, str(path), found)
    sources = [p for p in (ROOT / 'frontend').rglob('*.ts*') if 'node_modules' not in p.parts and '.next' not in p.parts]
    # Any read of a NEXT_PUBLIC_ variable would be inlined into browser bundles at build time.
    public_env = [str(p) for p in sources if re.search(r"env(\.|\[\s*['\"])NEXT_PUBLIC_", p.read_text())]
    server_modules = list((ROOT / 'frontend' / 'lib' / 'server').glob('*.ts'))
    unguarded = [str(p) for p in server_modules if 'import "server-only";' not in p.read_text()]
    assert not found, f'Secret exposed in: {found}'
    assert not public_env, f'NEXT_PUBLIC_ variables used in: {public_env}'
    assert not unguarded, f'Server modules without server-only guard: {unguarded}'
    return ['no-secret-in-responses-or-bundle'], len(urls), len([p for p in static if p.is_file()])


def verify_exports_protected_after_workflow(browser):
    """Brief exports and approved-report downloads exist now; they must still be protected."""
    context = browser.new_context()
    for path in ['/analyses/1/brief/pdf', '/analyses/1/brief/markdown', '/reports/1', '/reports/1/pdf',
                 '/reports/1/markdown', '/reports/1/html']:
        assert context.request.get(API + path).status == 401, path
        assert context.request.get(BACKEND + path).status == 401, path
    context.close()
    return ['brief-exports-and-approved-reports-protected']
