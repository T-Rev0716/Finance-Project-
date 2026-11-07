"""Browser acceptance check; requires built frontend and installed Chromium.

Runs isolated synthetic services and keeps screenshots under the requested folder.
Usage: python backend/scripts/verify_review_workflow.py [artifact-directory]
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
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


with tempfile.TemporaryDirectory() as temporary:
    log = open(OUT / 'services.log', 'w')
    try:
        env = {**os.environ, 'ADVISORLENS_DB': str(Path(temporary) / 'demo.db'),
               'ADVISORLENS_CORS_ORIGINS': 'http://127.0.0.1:3100',
               'ADVISORLENS_BRIEF_GENERATOR': 'deterministic-v1'}
        processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT/'backend', env=env, stdout=log, stderr=log))
        processes.append(subprocess.Popen(['npm', 'run', 'start', '--', '--hostname', '127.0.0.1', '--port', '3100'], cwd=ROOT/'frontend', env=env, stdout=log, stderr=log, start_new_session=True))
        ready('http://127.0.0.1:8000/health')
        ready('http://127.0.0.1:3100/workspace')
        with sync_playwright() as p:
            launch = {'executable_path': os.environ['ADVISORLENS_CHROMIUM_PATH']} if os.environ.get('ADVISORLENS_CHROMIUM_PATH') else {}
            browser = p.chromium.launch(**launch)
            page = browser.new_page(viewport={'width':1440, 'height':1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
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
            aid = page.request.get('http://127.0.0.1:8000/analyses').json()['analyses'][0]['id']
            item = page.request.get(f'http://127.0.0.1:8000/analyses/{aid}/reviews').json()['items'][0]
            endpoint = f"http://127.0.0.1:8000/analyses/{aid}/reviews/{item['finding_id']}"
            assert page.request.put(endpoint, data={'status':'discussed','note':'Saved from another tab.','expected_version':item['version']}).status == 200
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
            pdf = page.request.get(f'http://127.0.0.1:8000/analyses/{aid}/brief/pdf')
            assert pdf.status == 200 and pdf.body().startswith(b'%PDF')
            (OUT/'result.json').write_text(json.dumps({'status':'passed','checks':['save','reload','resolve-note-required','history','stale-update-conflict','mobile-overflow','no-page-errors','pdf-export']}))
            browser.close()
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        log.close()
