"""Client report browser acceptance: draft -> preview -> stale-source block -> approve -> download.

Called by verify_review_workflow.py after the household check, with the workspace showing
an analysis that already has a household snapshot attached.
"""
import hashlib
import io
import json
import re

from playwright.sync_api import expect
from pypdf import PdfReader

API = 'http://127.0.0.1:8000'
INTERNAL_NOTE = 'INTERNAL-ONLY: client mentioned a possible inheritance.'
CLIENT_TEXT = 'We will revisit position sizing at our next meeting.'


def _pdf_text(body):
    return re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(body)).pages))


def verify_client_report(page, out):
    page.set_viewport_size({'width': 1440, 'height': 1000})
    aid = page.request.get(f'{API}/analyses').json()['analyses'][0]['id']

    # An internal decision note saved through the review queue.
    card = page.get_by_role('article').first
    card.get_by_label('Review status').select_option('follow_up')
    card.get_by_label('Advisor note', exact=True).fill(INTERNAL_NOTE)
    card.get_by_role('button', name='Save review', exact=True).click()
    expect(card.get_by_role('status')).to_have_text('Review saved.')

    section = page.get_by_role('region', name='Client report')
    section.get_by_role('button', name='Prepare client report').click()
    summary = section.get_by_label('Client-facing summary', exact=True)
    expect(summary).not_to_have_value('')
    summary.fill(summary.input_value() + ' We focused on concentration in technology holdings.')
    section.get_by_role('checkbox').first.check()
    expect(section.get_by_text('Internal note (not included):')).to_be_visible()
    section.get_by_role('textbox', name=re.compile('^Client-facing text for')).fill(CLIENT_TEXT)
    section.get_by_role('checkbox', name=re.compile('^Include Browser test household')).check()
    section.get_by_role('checkbox', name='Priorities').check()
    section.get_by_role('checkbox', name=re.compile('^Account inventory')).check()
    section.scroll_into_view_if_needed()
    section.screenshot(path=str(out / 'report-draft.png'))

    section.get_by_role('button', name='Preview report').click()
    frame = page.frame_locator('iframe[title="Client report preview"]')
    expect(frame.get_by_text(CLIENT_TEXT, exact=False)).to_be_visible()
    expect(frame.get_by_text('DRAFT PREVIEW', exact=False)).to_be_visible()
    expect(frame.get_by_text('not reconciled', exact=False).first).to_be_visible()
    assert INTERNAL_NOTE not in frame.locator('body').inner_text()
    section.screenshot(path=str(out / 'report-preview.png'))

    # A review edited elsewhere after the preview must block approval.
    item = page.request.get(f'{API}/analyses/{aid}/reviews').json()['items'][0]
    assert page.request.put(f"{API}/analyses/{aid}/reviews/{item['finding_id']}", data={
        'status': 'discussed', 'note': INTERNAL_NOTE + ' (edited in another tab)',
        'expected_version': item['version']}).status == 200
    section.get_by_role('button', name='Approve and save report').click()
    expect(section.get_by_role('alert')).to_contain_text('changed')
    assert page.request.get(f'{API}/analyses/{aid}/reports').json()['reports'] == []
    section.screenshot(path=str(out / 'report-stale-blocked.png'))
    section.get_by_role('button', name='Reload latest sources').click()
    expect(section.get_by_role('status')).to_contain_text('Latest sources loaded')
    section.get_by_role('button', name='Preview report').click()
    expect(frame.get_by_text(CLIENT_TEXT, exact=False)).to_be_visible()
    section.get_by_role('button', name='Approve and save report').click()
    expect(section.get_by_role('status')).to_contain_text('Approved report #1 saved')
    section.screenshot(path=str(out / 'report-approved.png'))

    record = page.request.get(f'{API}/reports/1').json()
    downloads = {}
    for fmt, label in [('markdown', 'Markdown'), ('html', 'HTML'), ('pdf', 'PDF')]:
        with page.expect_download() as info:
            section.get_by_role('link', name=f'Download report 1 as {label}').click()
        body = open(info.value.path(), 'rb').read()
        assert hashlib.sha256(body).hexdigest() == record['files'][fmt], fmt
        downloads[fmt] = body
    assert downloads['pdf'].startswith(b'%PDF')
    texts = {'markdown': downloads['markdown'].decode(), 'html': downloads['html'].decode(),
             'pdf': _pdf_text(downloads['pdf'])}
    for fmt, text in texts.items():
        assert INTERNAL_NOTE.split(':')[0] not in text, f'internal note leaked into {fmt}'
        assert CLIENT_TEXT in text, fmt
        assert 'not reconciled' in text, fmt

    # Later source edits must not change the approved downloads.
    hid = record['sources']['household']['household_id']
    saved = page.request.get(f'{API}/households/{hid}').json()
    saved['profile']['priorities'] = 'Edited after the report was approved.'
    assert page.request.put(f'{API}/households/{hid}', data={
        'profile': saved['profile'], 'expected_version': saved['version']}).status == 200
    assert page.request.post(f'{API}/analyses/{aid}/brief').status == 200
    for fmt in downloads:
        assert page.request.get(f'{API}/reports/1/{fmt}').body() == downloads[fmt], f'{fmt} changed after edits'

    page.set_viewport_size({'width': 390, 'height': 844})
    section.scroll_into_view_if_needed()
    page.screenshot(path=str(out / 'report-mobile.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Report mobile overflow'
    (out / 'report-result.json').write_text(json.dumps({'status': 'passed', 'checks': [
        'internal-note-not-in-preview', 'stale-review-blocks-approval', 'reload-and-re-preview',
        'approve', 'download-markdown-html-pdf', 'downloads-match-stored-hashes',
        'internal-note-absent-from-all-formats', 'unreconciled-inventory-labelled',
        'downloads-unchanged-after-source-edits', 'mobile-overflow']}))
