def test_items_crud_and_filter(client):
    a = client.post('/api/items', json={'name': ' First '}).json()
    assert a['number'] == '#0001' and a['name'] == 'First' and a['status'] == 'open'
    client.post('/api/items', json={'name': 'Second'})
    assert client.post('/api/items', json={'name': ''}).status_code == 422

    client.patch(f"/api/items/{a['id']}", json={'status': 'done', 'notes': 'Finished'})
    assert [i['name'] for i in client.get('/api/items').json()] == ['Second']
    assert [i['name'] for i in client.get('/api/items?show=done').json()] == ['First']
    assert len(client.get('/api/items?show=all&q=sec').json()) == 1
    assert client.patch(f"/api/items/{a['id']}", json={'status': 'gone'}).status_code == 422

    assert client.patch(f"/api/items/{a['id']}", json={'priority': 3}).json()['priority'] == 3
    assert client.patch(f"/api/items/{a['id']}", json={'priority': None}).json()['priority'] is None
    assert client.patch(f"/api/items/{a['id']}", json={'name': None}).status_code == 400

    assert client.delete(f"/api/items/{a['id']}").status_code == 204
    assert client.get(f"/api/items/{a['id']}").status_code == 404


def test_secret_never_reaches_the_browser(client):
    s = client.put('/api/settings', json={'api_key': 'sk-test-1234567890'}).json()
    assert 'api_key' not in s and s['api_key_set'] and s['api_key_hint'] == '…7890'
    assert 'sk-test' not in client.get('/api/settings').text
    assert client.put('/api/settings', json={'nope': 1}).status_code == 400
    assert client.put('/api/settings', json={'page_size': 0}).status_code == 400


def test_migration_adds_columns_to_an_old_database(tmp_path):
    from __pkg__ import db
    path = str(tmp_path / 'old.db')
    with db.closing(db.connect(path)) as c:
        c.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', "
                  "notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        c.execute("INSERT INTO items (name, created_at, updated_at) VALUES ('kept', 'x', 'x')")
        c.commit()
    db.init(path)
    with db.closing(db.connect(path)) as c:
        cols = {r['name'] for r in c.execute('PRAGMA table_info(items)')}
        assert 'priority' in cols and c.execute('SELECT name FROM items').fetchone()['name'] == 'kept'


def test_health_busy_and_index(client):
    # (Not calling /api/shutdown here: it would stop the test process.)
    assert client.get('/api/health').json()['ok'] is True
    assert client.get('/api/busy').json() == {'busy': []}
    assert client.get('/').status_code == 200
