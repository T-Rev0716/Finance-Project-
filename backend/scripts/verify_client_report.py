"""Client report browser acceptance: draft -> preview -> stale-source block -> approve -> download.

Called by verify_review_workflow.py after the household check, with the workspace showing
an analysis that already has a household snapshot attached.
"""
import hashlib
import io
import json
import re

from playwright.sync_api import expect

from harness_api import SameSiteApi
from pypdf import PdfReader

INTERNAL_NOTE = 'INTERNAL-ONLY: client mentioned a possible inheritance.'
CLIENT_TEXT = 'We will revisit position sizing at our next meeting.'


def _pdf_text(body):
    return re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(body)).pages))


def _hold(page, pattern, method):
    """Intercept matching requests and keep them pending until the test releases them."""
    pending = []

    def handler(route):
        if route.request.method == method:
            pending.append(route)
        else:
            route.continue_()

    page.route(pattern, handler)
    return pending, handler


def _wait_until_held(page, pending):
    for _ in range(200):
        if pending:
            return
        page.wait_for_timeout(50)
    raise AssertionError('Request was never intercepted.')


def verify_client_report(page, out):
    api = SameSiteApi(page)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    aid = api.get(f'/analyses').json()['analyses'][0]['id']

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

    # A slow preview of an older draft must not come back as approvable.
    pending, handler = _hold(page, '**/reports/preview', 'POST')
    summary.fill('Summary A, requested first.')
    section.get_by_role('button', name='Preview report').click()
    _wait_until_held(page, pending)
    summary.fill('Summary B, edited while the preview was loading.')
    pending[0].continue_()
    expect(section.get_by_role('status')).to_contain_text('changed while the preview was loading')
    expect(page.locator('iframe[title="Client report preview"]')).to_have_count(0)
    expect(section.get_by_role('button', name='Approve and save report')).to_have_count(0)
    page.unroute('**/reports/preview', handler)

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
    item = api.get(f'/analyses/{aid}/reviews').json()['items'][0]
    assert api.put(f"/analyses/{aid}/reviews/{item['finding_id']}", data={
        'status': 'discussed', 'note': INTERNAL_NOTE + ' (edited in another tab)',
        'expected_version': item['version']}).status == 200
    section.get_by_role('button', name='Approve and save report').click()
    expect(section.get_by_role('alert')).to_contain_text('changed')
    assert api.get(f'/analyses/{aid}/reports').json()['reports'] == []
    section.screenshot(path=str(out / 'report-stale-blocked.png'))
    section.get_by_role('button', name='Reload latest sources').click()
    expect(section.get_by_role('status')).to_contain_text('Latest sources loaded')
    section.get_by_role('button', name='Preview report').click()
    expect(frame.get_by_text(CLIENT_TEXT, exact=False)).to_be_visible()
    expect(frame.get_by_text('Summary B, edited while the preview was loading.', exact=False)).to_be_visible()

    # The draft is locked while approval is in flight.
    pending, handler = _hold(page, '**/analyses/*/reports', 'POST')
    section.get_by_role('button', name='Approve and save report').click()
    _wait_until_held(page, pending)
    expect(summary).to_be_disabled()
    expect(section.get_by_role('checkbox').first).to_be_disabled()
    expect(section.get_by_role('textbox', name=re.compile('^Client-facing text for'))).to_be_disabled()
    pending[0].continue_()
    page.unroute('**/analyses/*/reports', handler)
    expect(section.get_by_role('status')).to_contain_text('Approved report #1 saved')
    expect(summary).to_be_enabled()
    section.screenshot(path=str(out / 'report-approved.png'))

    record = api.get(f'/reports/1').json()
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
    saved = api.get(f'/households/{hid}').json()
    saved['profile']['priorities'] = 'Edited after the report was approved.'
    assert api.put(f'/households/{hid}', data={
        'profile': saved['profile'], 'expected_version': saved['version']}).status == 200
    assert api.post(f'/analyses/{aid}/brief').status == 200
    for fmt in downloads:
        assert api.get(f'/reports/1/{fmt}').body() == downloads[fmt], f'{fmt} changed after edits'

    page.set_viewport_size({'width': 390, 'height': 844})
    section.scroll_into_view_if_needed()
    page.screenshot(path=str(out / 'report-mobile.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Report mobile overflow'

    _check_sources_refresh(page, out)
    (out / 'report-result.json').write_text(json.dumps({'status': 'passed', 'checks': [
        'delayed-older-preview-rejected', 'internal-note-not-in-preview', 'stale-review-blocks-approval',
        'reload-and-re-preview', 'draft-locked-during-approval', 'approve', 'download-markdown-html-pdf',
        'downloads-match-stored-hashes', 'internal-note-absent-from-all-formats',
        'unreconciled-inventory-labelled', 'downloads-unchanged-after-source-edits', 'mobile-overflow',
        'refresh-sources-keeps-draft', 'household-attach-refreshes-report-unselected']}))


def _check_sources_refresh(page, out):
    """Prepare a report first, then change sources; the draft wording must survive."""
    api = SameSiteApi(page)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('button', name='margaret retiree tech heavy', exact=True).click()
    expect(page.get_by_role('heading', name='margaret_retiree_tech_heavy.csv')).to_be_visible()
    aid = api.get(f'/analyses').json()['analyses'][0]['id']
    section = page.get_by_role('region', name='Client report')
    section.get_by_role('button', name='Prepare client report').click()
    expect(section.get_by_text('No household snapshot is attached', exact=False)).to_be_visible()
    summary = section.get_by_label('Client-facing summary', exact=True)
    summary.fill('Summary written before the household was attached.')
    section.get_by_role('checkbox').first.check()
    follow_up = section.get_by_role('textbox', name=re.compile('^Client-facing text for'))
    follow_up.fill('Follow-up written before refreshing.')

    # Ordinary refresh after a review changed elsewhere.
    item = api.get(f'/analyses/{aid}/reviews').json()['items'][0]
    assert api.put(f"/analyses/{aid}/reviews/{item['finding_id']}", data={
        'status': 'discussed', 'note': 'Changed in another tab.', 'expected_version': item['version']}).status == 200
    section.get_by_role('button', name='Refresh sources').click()
    expect(section.get_by_text('· Discussed', exact=False).first).to_be_visible()
    expect(summary).to_have_value('Summary written before the household was attached.')
    expect(follow_up).to_have_value('Follow-up written before refreshing.')

    # Attaching a household above the report makes it available, but not selected.
    hid = api.get(f'/households').json()['households'][0]['id']
    page.get_by_label('Saved household', exact=True).select_option(str(hid))
    page.get_by_role('button', name='Attach snapshot', exact=True).click()
    page.get_by_role('group', name='Confirm household attachment').get_by_role(
        'button', name='Confirm permanent attachment', exact=True).click()
    include = section.get_by_role('checkbox', name=re.compile('^Include '))
    expect(include).to_be_visible()
    expect(include).not_to_be_checked()
    expect(section.get_by_role('status')).to_contain_text('household snapshot is now available')
    expect(summary).to_have_value('Summary written before the household was attached.')
    expect(follow_up).to_have_value('Follow-up written before refreshing.')
    section.scroll_into_view_if_needed()
    section.screenshot(path=str(out / 'report-household-refreshed.png'))
