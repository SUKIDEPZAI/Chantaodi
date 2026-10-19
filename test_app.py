"""Kiểm thử tích hợp (provider được MOCK, không gọi MộtAPI thật). Chạy: python -m unittest -v test_app"""
import os, sys, io, tempfile, unittest
from types import SimpleNamespace as NS
_d = tempfile.mkdtemp(); os.environ.update(DATABASE_PATH=_d + '/t.db', WORKSPACE_DIR=_d + '/ws', MOTAPIS_API_KEY='test')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server
CALLS = []
class _Fake:
    class chat:
        class completions:
            @staticmethod
            def create(**p):
                CALLS.append(p)
                return iter([NS(choices=[NS(delta=NS(content=t, reasoning_content=None))]) for t in ('Xin ', 'chào')])
server.client = lambda: _Fake
A = {'X-Session': 'sessionAAAA1'}; B = {'X-Session': 'sessionBBBB2'}; c = server.app.test_client()
def chat(h, msg='hi', **f): return c.post('/api/chat', headers=h, data={'message': msg, 'model': 'm', **f}).get_data(as_text=True)
def msgs(h, cid): return c.get('/api/v2/conversations/' + cid, headers=h).get_json()['messages']
def sysprompt(): return CALLS[-1]['messages'][0]['content']

class T(unittest.TestCase):
    def test_persist_and_restore(self):
        out = chat(A, conv_id='conv-persist-1', client_id='cm-0001', title='Tiêu đề')
        self.assertIn('"token"', out)
        m = msgs(A, 'conv-persist-1'); self.assertEqual([x['role'] for x in m], ['user', 'assistant']); self.assertEqual(m[1]['content'], 'Xin chào')
    def test_retry_does_not_duplicate_user_message(self):
        for _ in range(2): chat(A, conv_id='conv-retry-001', client_id='cm-dup-1')
        self.assertEqual(sum(1 for x in msgs(A, 'conv-retry-001') if x['role'] == 'user'), 1)
    def test_regen_replaces_last_turn(self):
        chat(A, conv_id='conv-regen-001', client_id='cm-r1'); chat(A, conv_id='conv-regen-001', client_id='cm-r2', regen='1')
        self.assertEqual([x['role'] for x in msgs(A, 'conv-regen-001')], ['user', 'assistant'])
    def test_owner_isolation(self):
        chat(A, conv_id='conv-owner-001', client_id='cm-o1')
        self.assertEqual(c.get('/api/v2/conversations/conv-owner-001', headers=B).status_code, 404)
        self.assertEqual(c.delete('/api/v2/conversations/conv-owner-001', headers=B).status_code, 404)
        self.assertEqual(c.post('/api/chat', headers=B, data={'message': 'x', 'model': 'm', 'conv_id': 'conv-owner-001'}).status_code, 403)
        self.assertEqual(len(msgs(A, 'conv-owner-001')), 2)
    def test_project_instructions_scoped(self):
        pid = c.post('/api/v2/projects', headers=A, json={'name': 'P', 'instructions': 'LUON_TRA_LOI_BANG_THO'}).get_json()['id']
        chat(A, conv_id='conv-proj-0001', client_id='cm-p1', project_id=pid); self.assertIn('LUON_TRA_LOI_BANG_THO', sysprompt())
        chat(B, conv_id='conv-proj-0002', client_id='cm-p2', project_id=pid); self.assertNotIn('LUON_TRA_LOI_BANG_THO', sysprompt())
        self.assertEqual(c.get('/api/v2/projects/' + pid, headers=B).status_code, 404)
        self.assertEqual(c.get('/api/v2/projects', headers=B).get_json()['items'], [])
    def test_project_files_scoped_and_traversal(self):
        up = c.post('/api/files/upload', headers=A, data={'files': (io.BytesIO('BI_MAT_TAI_LIEU'.encode()), 'ghi-chu.txt')}, content_type='multipart/form-data'); self.assertTrue(up.get_json()['ok'])
        pid = c.post('/api/v2/projects', headers=A, json={'name': 'F'}).get_json()['id']
        got = c.put(f'/api/v2/projects/{pid}/files', headers=A, json={'paths': ['ghi-chu.txt', '../../etc/passwd', 'khong-co.txt']}).get_json()['paths']
        self.assertEqual(got, ['ghi-chu.txt'])
        chat(A, conv_id='conv-file-0001', client_id='cm-f1', project_id=pid)
        self.assertIn('BI_MAT_TAI_LIEU', CALLS[-1]['messages'][-1]['content'][0]['text'])
        self.assertEqual(c.put(f'/api/v2/projects/{pid}/files', headers=B, json={'paths': ['ghi-chu.txt']}).status_code, 404)
    def test_search_escapes_wildcards(self):
        chat(A, msg='giảm 100% hôm nay', conv_id='conv-srch-0001', client_id='cm-s1'); chat(A, msg='xin chao', conv_id='conv-srch-0002', client_id='cm-s2')
        ids = [x['id'] for x in c.get('/api/v2/conversations?q=%25', headers=A).get_json()['items']]
        self.assertEqual(ids, ['conv-srch-0001'])
    def test_pin_rename_archive_delete(self):
        chat(A, conv_id='conv-mgmt-0001', client_id='cm-m1'); u = '/api/v2/conversations/conv-mgmt-0001'
        c.patch(u, headers=A, json={'title': 'Mới', 'pinned': True}); it = c.get('/api/v2/conversations', headers=A).get_json()['items'][0]
        self.assertEqual((it['id'], it['title'], it['pinned']), ('conv-mgmt-0001', 'Mới', 1))
        c.patch(u, headers=A, json={'archived': True}); self.assertNotIn('conv-mgmt-0001', [x['id'] for x in c.get('/api/v2/conversations', headers=A).get_json()['items']])
        self.assertEqual(c.delete(u, headers=A).status_code, 200); self.assertEqual(c.get(u, headers=A).status_code, 404)
    def test_artifact_versions(self):
        aid = c.post('/api/v2/artifacts', headers=A, json={'title': 't', 'lang': 'html', 'content': '<p>1</p>'}).get_json()['id']
        c.post(f'/api/v2/artifacts/{aid}/versions', headers=A, json={'content': '<p>2</p>'})
        self.assertTrue(c.post(f'/api/v2/artifacts/{aid}/versions', headers=A, json={'content': '<p>2</p>'}).get_json().get('unchanged'))
        a = c.get(f'/api/v2/artifacts/{aid}', headers=A).get_json(); self.assertEqual((len(a['versions']), a['content']), (2, '<p>2</p>'))
        self.assertEqual(c.get(f"/api/v2/artifacts/{aid}/versions/{a['versions'][0]['id']}", headers=A).get_json()['content'], '<p>1</p>')
        self.assertEqual(c.get(f'/api/v2/artifacts/{aid}', headers=B).status_code, 404)
    def test_rate_limit(self):
        H = {'X-Session': 'sessionRATE99'}; codes = [c.post('/api/chat', headers=H, data={'message': 'x', 'model': 'm'}).status_code for _ in range(32)]
        self.assertEqual(codes[:30], [200] * 30); self.assertEqual(codes[-1], 429)
    def test_import_old_localstorage(self):
        r = c.post('/api/v2/import', headers=A, json={'chats': [{'id': 'c-1700000000-abcde', 'title': 'Cũ', 'history': [{'role': 'user', 'content': 'a'}, {'role': 'assistant', 'content': 'b'}]}, {'id': '../x', 'title': 'bad'}]}).get_json()
        self.assertEqual(r['imported'], 1); self.assertEqual(len(msgs(A, 'c-1700000000-abcde')), 2)

if __name__ == '__main__': unittest.main()
