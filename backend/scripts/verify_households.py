"""Household browser acceptance, called by the isolated workflow harness."""
import json
from playwright.sync_api import expect


def verify_households(page, out):
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://127.0.0.1:3100/households')
    page.get_by_role('button',name='Use fictional example',exact=True).click()
    page.get_by_label('Household name',exact=True).fill('Browser test household')
    page.get_by_role('button',name='Save household',exact=True).click()
    expect(page.get_by_role('status')).to_have_text('Household saved · version 1.')
    summary=page.get_by_role('region',name='Saved household summary')
    expect(summary.get_by_text('$560,000',exact=True)).to_be_visible()
    expect(summary.get_by_text('$2,600',exact=True)).to_be_visible()
    page.reload()
    page.get_by_role('button',name='Browser test household Version 1',exact=True).click()
    expect(page.get_by_label('Household name',exact=True)).to_have_value('Browser test household')
    expect(page.get_by_label('Goal 2 target amount (USD)',exact=True)).to_have_value('')
    page.get_by_label('Cash flow 4 amount (USD)',exact=True).fill('')
    complete=page.get_by_role('checkbox',name='I have reviewed the income and spending inventory for completeness.')
    expect(complete).not_to_be_checked()
    expect(complete).to_be_disabled()
    page.get_by_role('button',name='Save household',exact=True).click()
    expect(page.get_by_role('status')).to_have_text('Household saved · version 2.')
    expect(summary.get_by_role('paragraph').filter(has_text='Not established')).to_be_visible()
    page.get_by_label('Cash flow 4 amount (USD)',exact=True).fill('12000')
    complete.check()
    page.get_by_role('button',name='Save household',exact=True).click()
    expect(page.get_by_role('status')).to_have_text('Household saved · version 3.')
    expect(summary.get_by_text('$2,600',exact=True)).to_be_visible()
    page.get_by_role('button',name='Load saved versions',exact=True).click()
    expect(page.locator('summary').filter(has_text='Version 1 ·')).to_be_visible()
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(out/'household-desktop.png'),full_page=True)
    page.screenshot(path=str(out/'household-overview.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(out/'household-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Household mobile overflow'

    hid=page.request.get('http://127.0.0.1:8000/households').json()['households'][0]['id']
    saved=page.request.get(f'http://127.0.0.1:8000/households/{hid}').json()
    saved['profile']['priorities']='Changed in another session.'
    assert page.request.put(f'http://127.0.0.1:8000/households/{hid}',data={'profile':saved['profile'],'expected_version':3}).status==200
    page.get_by_label('Priorities and values',exact=True).fill('Keep this unsaved draft.')
    page.get_by_role('button',name='Save household',exact=True).click()
    expect(page.get_by_role('main').get_by_role('alert')).to_contain_text('updated elsewhere')
    expect(page.get_by_label('Priorities and values',exact=True)).to_have_value('Keep this unsaved draft.')
    page.once('dialog',lambda dialog:dialog.accept())
    page.get_by_role('button',name='Discard draft and load latest household',exact=True).click()
    expect(page.get_by_label('Priorities and values',exact=True)).to_have_value('Changed in another session.')

    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('link',name='Portfolio workspace',exact=True).click()
    page.get_by_role('button',name='growth concentrated',exact=True).click()
    page.get_by_label('Saved household',exact=True).select_option(str(hid))
    page.get_by_role('button',name='Attach snapshot',exact=True).click()
    confirm=page.get_by_role('group',name='Confirm household attachment')
    expect(confirm).to_contain_text('Browser test household')
    expect(confirm).to_contain_text('growth_concentrated.csv')
    confirm.get_by_role('button',name='Cancel',exact=True).click()
    expect(confirm).to_be_hidden()
    assert page.request.get(f'http://127.0.0.1:8000/analyses/{page.request.get("http://127.0.0.1:8000/analyses").json()["analyses"][0]["id"]}/household').json()['context'] is None
    page.get_by_role('button',name='Attach snapshot',exact=True).click()
    confirm.scroll_into_view_if_needed()
    page.screenshot(path=str(out/'household-confirm.png'))
    confirm.get_by_role('button',name='Confirm permanent attachment',exact=True).click()
    expect(page.get_by_text('Browser test household · version 4',exact=True)).to_be_visible()
    saved=page.request.get(f'http://127.0.0.1:8000/households/{hid}').json()
    saved['profile']['name']='Later household name'
    assert page.request.put(f'http://127.0.0.1:8000/households/{hid}',data={'profile':saved['profile'],'expected_version':4}).status==200
    page.reload()
    page.get_by_role('button',name='history',exact=True).click()
    page.get_by_role('button',name='Open',exact=True).first.click()
    expect(page.get_by_text('Browser test household · version 4',exact=True)).to_be_visible()
    expect(page.get_by_text('Changed in another session.',exact=True)).to_be_visible()
    page.screenshot(path=str(out/'household-attached.png'))
    (out/'household-result.json').write_text(json.dumps({'status':'passed','checks':[
        'create','reload','unknown-versus-zero','irregular-expense-conversion','inventory-confirmation',
        'history','stale-update-conflict','mobile-overflow','attach-requires-confirmation',
        'analysis-snapshot-remains-frozen']}))
