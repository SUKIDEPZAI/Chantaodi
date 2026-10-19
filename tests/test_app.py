"""API-level regression tests. AI/search providers are mocked; these tests never spend API credit."""
import os, sys, tempfile, unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = os.path.join(_tmp.name, "test.sqlite3")
os.environ["WORKSPACE_DIR"] = os.path.join(_tmp.name, "workspace")
os.environ["MOTAPIS_API_KEY"] = "test-key"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as service

A={"X-Session":"session_owner_A_1234567890"}
B={"X-Session":"session_owner_B_1234567890"}

class FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                if kwargs.get("stream"):
                    return iter([NS(choices=[NS(delta=NS(content="Xin ",reasoning_content="internal reasoning sentinel"))]), NS(choices=[NS(delta=NS(content="chào"))])])
                return NS(choices=[NS(message=NS(content="OK"))])

class AppTests(unittest.TestCase):
    def setUp(self): self.client=service.app.test_client()

    def test_health_never_leaks_api_key(self):
        r=self.client.get("/api/health");self.assertEqual(r.status_code,200);self.assertTrue(r.get_json()["ai_configured"]);self.assertNotIn("test-key",r.get_data(as_text=True))

    def test_search_endpoint_returns_provider_diagnostics(self):
        expected={"available":False,"results":[],"providers":[],"failed_providers":["DuckDuckGo"],"note":"blocked"}
        with patch.object(service,"web_search",return_value=expected) as search:
            r=self.client.post("/api/search",headers=A,json={"query":"my query","deep":True})
        self.assertEqual(r.status_code,200);self.assertFalse(r.get_json()["available"]);self.assertEqual(r.get_json()["note"],"blocked")
        search.assert_called_once_with("my query",8,deep=True)

    def test_search_empty_input_is_400(self):
        r=self.client.post("/api/search",headers=A,json={"query":""});self.assertEqual(r.status_code,400)

    def test_conversation_isolation_by_session(self):
        with patch.object(service,"ai_client",return_value=FakeClient):
            r=self.client.post("/api/chat",headers=A,data={"message":"hello","model":"m","conv_id":"c-owner-isolation-12345678","client_id":"client-0001"})
            self.assertEqual(r.status_code,200);self.assertIn('Xin',r.get_data(as_text=True));self.assertNotIn("internal reasoning sentinel",r.get_data(as_text=True))
        mine=self.client.get("/api/conversations/c-owner-isolation-12345678",headers=A)
        other=self.client.get("/api/conversations/c-owner-isolation-12345678",headers=B)
        self.assertEqual(mine.status_code,200);self.assertEqual(other.status_code,404)
        self.assertEqual([m["role"] for m in mine.get_json()["messages"]],["user","assistant"])

    def test_project_owner_isolation(self):
        created=self.client.post("/api/projects",headers=A,json={"name":"Project A"})
        self.assertEqual(created.status_code,201);pid=created.get_json()["id"]
        found=self.client.get("/api/projects",headers=A).get_json()["items"]
        other=self.client.get("/api/projects",headers=B).get_json()["items"]
        self.assertEqual(len(found),1);self.assertEqual(other,[])
        denied=self.client.patch("/api/projects/"+pid,headers=B,json={"name":"takeover"})
        self.assertEqual(denied.status_code,404)

    def test_workspace_zip_does_not_extract_path_traversal(self):
        import io, zipfile
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            z.writestr("safe/readme.txt","safe")
            z.writestr("../../escape.txt","not safe")
        buf.seek(0)
        result=self.client.post("/api/files",headers=A,data={"files":(buf,"bundle.zip")},content_type="multipart/form-data")
        self.assertEqual(result.status_code,201)
        payload=result.get_json();self.assertTrue(any(x["path"].endswith("readme.txt") for x in payload["files"]))
        self.assertFalse(any("escape.txt" in x["path"] for x in payload["files"]))

    def test_workspace_upload_read_download_delete(self):
        up=self.client.post("/api/files",headers=A,data={"files":( __import__('io').BytesIO(b'hello file'),"notes.txt")},content_type="multipart/form-data")
        self.assertEqual(up.status_code,201)
        read=self.client.get("/api/files/read?path=notes.txt",headers=A)
        self.assertEqual(read.get_json()["text"],"hello file")
        download=self.client.get("/api/files/download?path=notes.txt",headers=A)
        self.assertEqual(download.status_code,200)
        deleted=self.client.delete("/api/files?path=notes.txt",headers=A)
        self.assertEqual(deleted.status_code,200)

if __name__=="__main__":unittest.main()
