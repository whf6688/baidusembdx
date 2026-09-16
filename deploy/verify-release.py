"""Read-only post-release checks through the loopback application gateway."""
import json
import os
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


BASE_URL = 'http://127.0.0.1:18080/api/v1'
opener = build_opener(HTTPCookieProcessor(CookieJar()))


def login():
    username = os.environ.get('VERIFY_USERNAME', 'admin')
    password = os.environ.get('VERIFY_PASSWORD')
    if not password:
        raise SystemExit('VERIFY_PASSWORD is required for authenticated release checks')
    payload = json.dumps({'username': username, 'password': password}).encode()
    request = Request(
        BASE_URL + '/auth/login',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with opener.open(request, timeout=30) as response:
        assert json.load(response)['status'] == 'ok'


def get(path):
    request = Request(BASE_URL + path)
    with opener.open(request, timeout=90) as response:
        result = json.load(response)
    assert result['status'] == 'ok', path
    return result['data']


with urlopen(BASE_URL + '/health', timeout=30) as response:
    health = json.load(response)['data']
print('health=ok', flush=True)
login()
projects = get('/projects')
assert projects, 'No projects returned'
for project in projects:
    prefix = '/projects/' + project['id']
    first = get(prefix + '/material-keywords?page=1&page_size=20')
    second = get(prefix + '/material-keywords?page=2&page_size=20')
    assert first['page'] == 1 and second['page'] == 2
    if first['total'] > 20:
        assert second['items']
        assert not ({item['id'] for item in first['items']} & {item['id'] for item in second['items']})
    print('materials_total=' + str(first['total']) + '; pagination=ok', flush=True)
    accounts = get(prefix + '/account-workspace?page=1&page_size=20')
    print('account_workspace=ok', flush=True)
    assert get('/session')['username']
    print('web_session=ok', flush=True)
print('verification=passed', flush=True)
