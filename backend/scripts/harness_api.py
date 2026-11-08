"""Shared helpers for the browser acceptance harness (protection enabled)."""
from playwright.sync_api import expect

APP_ORIGIN = 'http://127.0.0.1:3100'
API = f'{APP_ORIGIN}/api'
BACKEND = 'http://127.0.0.1:8000'
COOKIE_NAME = 'advisorlens-session'  # The __Host- prefixed name is used only in production.


class SameSiteApi:
    """Calls the app's authenticated API routes with the page's session cookie, as another
    tab of the same site would: same Origin, current CSRF token."""

    def __init__(self, page):
        self.request = page.request

    def _headers(self):
        token = self.request.get(f'{API}/auth/session').json()['csrfToken']
        return {'Origin': APP_ORIGIN, 'X-CSRF-Token': token}

    def get(self, path):
        return self.request.get(API + path)

    def post(self, path, data=None):
        return self.request.post(API + path, data=data, headers=self._headers())

    def put(self, path, data):
        return self.request.put(API + path, data=data, headers=self._headers())


def sign_in(page, password, next_path='/workspace'):
    page.goto(f'{APP_ORIGIN}{next_path}')
    expect(page).to_have_url(f'{APP_ORIGIN}/login?next={next_path.replace("/", "%2F")}')
    page.get_by_label('Demo password', exact=True).fill(password)
    page.get_by_role('button', name='Sign in', exact=True).click()
    expect(page).to_have_url(f'{APP_ORIGIN}{next_path}')
