import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "skills/storytelling/publishing/wechat.py"
spec = importlib.util.spec_from_file_location("wechat_adapter", MODULE)
wechat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wechat)


class FakeTransport:
    def __init__(self, result=None, failure=None):
        self.calls = []
        self.result = result or {"media_id": "draft-example"}
        self.failure = failure

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if url.endswith("stable_token"):
            return {"access_token": "TEST_ONLY_TOKEN", "expires_in": 7200}
        if self.failure:
            raise self.failure
        return self.result


def draft(content="<p>Original explanatory text.</p>"):
    return {"articles": [{"title": "Example", "content": content, "thumb_media_id": "cover-example"}]}


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def client(self, transport, account="test-account"):
        return wechat.WeChat(account, "TEST_ONLY_SECRET", self.root, transport)

    def test_preview_does_not_read_credentials_or_call_network(self):
        payload = self.root / "article.json"
        payload.write_text(json.dumps(draft()))
        with patch.dict(os.environ, {}, clear=True), patch.object(wechat, "WeChat") as client:
            code = wechat.main(["draft", str(payload), "--preview-out", str(self.root / "preview.html")])
            self.assertEqual(code, 0)
            client.assert_not_called()
        self.assertIn("Original explanatory", (self.root / "preview.html").read_text())

    def test_create_draft_is_not_publication(self):
        transport = FakeTransport()
        result = self.client(transport).run("draft", draft())
        self.assertEqual(result["state"], "draft")
        self.assertEqual(len(transport.calls), 2)
        self.assertIn("/draft/add?", transport.calls[-1][1])
        self.assertNotIn("freepublish", str(transport.calls))

    def test_success_receipt_prevents_duplicate_request(self):
        transport = FakeTransport()
        client = self.client(transport)
        result = client.run("draft", draft())
        again = client.run("draft", draft())
        self.assertEqual(result["media_id"], again["media_id"])
        self.assertTrue(again["reused_receipt"])
        self.assertEqual(len(transport.calls), 2)

    def test_same_content_in_different_accounts_is_not_reused(self):
        transport = FakeTransport()
        self.client(transport, "account-one").run("draft", draft())
        self.client(transport, "account-two").run("draft", draft())
        self.assertEqual(len(transport.calls), 4)

    def test_unknown_outcome_blocks_retry(self):
        transport = FakeTransport(failure=wechat.AdapterError("Transport error"))
        client = self.client(transport)
        with self.assertRaises(wechat.AdapterError):
            client.run("draft", draft())
        with self.assertRaisesRegex(wechat.AdapterError, "unknown"):
            client.run("draft", draft())
        self.assertEqual(len(transport.calls), 2)
        receipt = json.loads(next(self.root.rglob("*.json")).read_text())
        self.assertEqual(receipt["state"], "unknown")

    def test_rejected_response_does_not_log_echoed_credentials(self):
        transport = FakeTransport({"errcode": 48001, "errmsg": "TEST_ONLY_TOKEN TEST_ONLY_SECRET"})
        with self.assertRaisesRegex(wechat.RemoteRejected, "48001") as error:
            self.client(transport).run("draft", draft())
        self.assertNotIn("TEST_ONLY", str(error.exception))
        receipt = next(self.root.rglob("*.json")).read_text()
        self.assertNotIn("TEST_ONLY", receipt)
        self.assertNotIn("Original explanatory", receipt)
        self.assertNotIn("test-account", receipt)

    def test_publish_requires_existing_authorization(self):
        transport = FakeTransport({"publish_id": "job-example"})
        client = self.client(transport)
        with self.assertRaises(wechat.AdapterError):
            client.run("publish", {"media_id": "draft-example"})
        self.assertFalse(transport.calls)
        result = client.run("publish", {"media_id": "draft-example"}, authorized=True)
        self.assertEqual(result["state"], "submitted")
        self.assertEqual(result["publish_id"], "job-example")

    def test_status_distinguishes_pending_and_published(self):
        transport = FakeTransport({"publish_status": 1})
        client = self.client(transport)
        self.assertEqual(client.run("status", {"publish_id": "job"})["state"], "not_confirmed_published")
        transport.result = {"publish_status": 0, "article_detail": {"item": [
            {"article_url": "https://mp.weixin.qq.com/s/example"},
            {"article_url": "https://mp.weixin.qq.com/s?tempkey=SECRET"}]}}
        result = client.run("status", {"publish_id": "job"})
        self.assertEqual(result["state"], "published")
        self.assertEqual(result["article_urls"], ["https://mp.weixin.qq.com/s/example"])

    def test_live_article_rejects_missing_images_instead_of_silently_dropping(self):
        with self.assertRaises(wechat.AdapterError):
            wechat.validate_draft(draft('<img src="local-chart.png">'), live=True)
        wechat.validate_draft(draft('<img src="https://mmbiz.qpic.cn/mmbiz_png/example">'), live=True)

    def test_preview_rejects_active_html(self):
        for content in ('<script>alert(1)</script>', '<img src="x" onerror="alert(1)">',
                        '<a href="javascript:alert(1)">x</a>', '<iframe src="https://example.com"></iframe>'):
            with self.subTest(content=content), self.assertRaises(wechat.AdapterError):
                wechat.validate_draft(draft(content))

    def test_preview_copies_images_relative_to_article_json_to_arbitrary_output(self):
        article_dir = self.root / "release/wechat-article"
        media_dir = article_dir / "media"
        media_dir.mkdir(parents=True)
        image = media_dir / "01 chart.png"
        image.write_bytes(b"test-only-image-bytes")
        article_file = article_dir / "article.json"
        original = json.dumps(draft('<p>A &amp; B</p><img src="media/01%20chart.png" alt="A &amp; B">'))
        article_file.write_text(original)
        destination = self.root / "elsewhere/review.html"
        with patch.object(wechat, "WeChat") as client:
            code = wechat.main(["preview", str(article_file), "--preview-out", str(destination)])
            client.assert_not_called()
        self.assertEqual(code, 0)
        copied = next((destination.parent / "review-assets").glob("*.png"))
        self.assertEqual(copied.read_bytes(), image.read_bytes())
        self.assertIn('src="review-assets/' + copied.name + '"', destination.read_text())
        self.assertIn("A &amp; B", destination.read_text())
        self.assertEqual(article_file.read_text(), original)

    def test_preview_missing_local_image_fails_without_network(self):
        article_file = self.root / "article.json"
        article_file.write_text(json.dumps(draft('<img src="media/missing.png">')))
        with patch.object(wechat, "WeChat") as client:
            code = wechat.main(["preview", str(article_file), "--preview-out", str(self.root / "elsewhere/preview.html")])
            client.assert_not_called()
        self.assertEqual(code, 1)
        self.assertFalse((self.root / "elsewhere/preview.html").exists())

    def test_upload_uses_multipart_and_safe_filename(self):
        image = self.root / 'private-name.png'
        image.write_bytes(b"example media")
        transport = FakeTransport({"url": "https://mmbiz.qpic.cn/mmbiz_png/example"})
        result = self.client(transport).run("upload-body", media_path=image)
        self.assertEqual(result["state"], "uploaded")
        request = transport.calls[-1]
        self.assertIn('name="media"', request[3].decode())
        self.assertNotIn("private-name", request[3].decode())
        self.assertIn("multipart/form-data", request[2]["Content-Type"])

    def test_corrupt_receipt_fails_closed(self):
        transport = FakeTransport()
        client = self.client(transport)
        client.run("draft", draft())
        next(self.root.rglob("*.json")).write_text("broken json")
        with self.assertRaises(ValueError):
            client.run("draft", draft())
        self.assertEqual(len(transport.calls), 2)

    def test_credentials_exist_only_in_transport_not_receipts(self):
        transport = FakeTransport({"media_id": "draft-example", "access_token": "TEST_ONLY_TOKEN"})
        self.client(transport).run("draft", draft())
        result = next(self.root.rglob("*.json"))
        self.assertEqual(result.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("TEST_ONLY", result.read_text())

    def test_upload_hash_matches_snapshot_if_source_changes_during_auth(self):
        image = self.root / "chart.png"
        image.write_bytes(b"first-version")
        transport = FakeTransport({"url": "https://mmbiz.qpic.cn/mmbiz_png/example"})

        def changing_transport(method, url, headers, body):
            if url.endswith("stable_token"):
                image.write_bytes(b"second-version")
            return transport(method, url, headers, body)

        self.client(changing_transport).run("upload-body", media_path=image)
        receipt = json.loads(next(self.root.rglob("*.json")).read_text())
        self.assertEqual(receipt["content_sha256"], wechat.digest(b"first-version"))
        self.assertIn(b"first-version", transport.calls[-1][3])
        self.assertNotIn(b"second-version", transport.calls[-1][3])


if __name__ == "__main__":
    unittest.main()
