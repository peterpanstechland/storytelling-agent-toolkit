#!/usr/bin/env python3
"""WeChat Official Account adapter. Python 3.10+, standard library only.

All CLI operations preview unless --execute is present. A publish operation also
requires --authorized, an assertion of existing human authorization for that draft.
No tokens, secrets, account identifiers, or source bodies are written to receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.weixin.qq.com"
ENDPOINTS = {
    "upload-body": "/cgi-bin/media/uploadimg",
    "upload-cover": "/cgi-bin/material/add_material",
    "draft": "/cgi-bin/draft/add",
    "get-draft": "/cgi-bin/draft/get",
    "publish": "/cgi-bin/freepublish/submit",
    "status": "/cgi-bin/freepublish/get",
}
MUTATIONS = {"upload-body", "upload-cover", "draft", "publish"}


class AdapterError(Exception):
    """Safe-to-print error: never include raw HTTP errors, URLs or response bodies."""


class RemoteRejected(AdapterError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AdapterError("API redirect refused; no credential was forwarded")


def http_transport(method, url, headers, body):
    """Fixed-origin HTTPS; errors do not expose token-bearing request URLs."""
    if urllib.parse.urlsplit(url).netloc != "api.weixin.qq.com":
        raise AdapterError("Unexpected API host")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=40) as response:
            result = json.loads(response.read())
    except AdapterError:
        raise
    except urllib.error.HTTPError as exc:
        raise AdapterError(f"HTTP {exc.code}; request outcome may be unknown") from None
    except (OSError, ValueError, urllib.error.URLError):
        raise AdapterError("Transport or JSON error; request outcome may be unknown") from None
    if not isinstance(result, dict):
        raise AdapterError("Unexpected API response shape")
    return result


class SafeHTML(HTMLParser):
    ALLOWED = set("p section div span strong b em i u s br hr blockquote h1 h2 h3 h4 h5 h6 ul ol li pre code a img table thead tbody tr td th figure figcaption sup sub".split())

    def __init__(self, live=False):
        super().__init__(convert_charrefs=True)
        self.live = live

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED:
            raise AdapterError(f"Unsupported HTML element: {tag}")
        attrs = dict(attrs)
        for name, value in attrs.items():
            value = value or ""
            if name.lower().startswith("on") or name in {"srcdoc", "srcset", "background"}:
                raise AdapterError("Active HTML attributes are not allowed")
            if name == "style" and any(x in value.lower() for x in ("url(", "expression", "@import")):
                raise AdapterError("CSS resource/expression references are not allowed")
            if name in {"href", "src"}:
                scheme = urllib.parse.urlsplit(value).scheme.lower()
                if scheme and scheme not in {"http", "https"}:
                    raise AdapterError("Unsupported link/image URL scheme")
        if tag == "img":
            src = attrs.get("src", "")
            if not src:
                raise AdapterError("Every image needs a src")
            if self.live:
                parts = urllib.parse.urlsplit(src)
                if parts.scheme not in {"http", "https"} or parts.hostname != "mmbiz.qpic.cn":
                    raise AdapterError("Upload each body image first and use its returned WeChat CDN URL")


def validate_draft(payload, live=False):
    if not isinstance(payload, dict) or set(payload) != {"articles"}:
        raise AdapterError("Draft JSON must contain only articles")
    if not isinstance(payload["articles"], list) or not payload["articles"]:
        raise AdapterError("articles must be a nonempty list")
    allowed = {"article_type", "title", "author", "digest", "content", "content_source_url",
               "thumb_media_id", "need_open_comment", "only_fans_can_comment",
               "pic_crop_235_1", "pic_crop_1_1"}
    for article in payload["articles"]:
        if not isinstance(article, dict) or set(article) - allowed:
            raise AdapterError("Unsupported article fields; this adapter implements news articles")
        for key in ("title", "content", "thumb_media_id"):
            if not isinstance(article.get(key), str) or not article[key].strip():
                raise AdapterError(f"Nonempty article {key} is required")
        if article.get("article_type", "news") != "news":
            raise AdapterError("This adapter implements article_type=news")
        for key in ("need_open_comment", "only_fans_can_comment"):
            if key in article and article[key] not in (0, 1):
                raise AdapterError(f"{key} must be 0 or 1")
        SafeHTML(live).feed(article["content"])
    return payload


class PreviewImages(HTMLParser):
    """Copy local image snapshots beside the preview without changing source JSON."""

    def __init__(self, source_dir, destination):
        super().__init__(convert_charrefs=False)
        self.source_dir = Path(source_dir).resolve()
        self.destination = Path(destination).resolve()
        self.output = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            self.output.append(self.get_starttag_text())
            return
        rebuilt = []
        for key, value in attrs:
            if key == "src" and value:
                parts = urllib.parse.urlsplit(value)
                if not parts.scheme and not parts.netloc:
                    source = Path(urllib.parse.unquote(parts.path))
                    if not source.is_absolute():
                        source = self.source_dir / source
                    source = source.resolve()
                    if not source.is_file():
                        raise AdapterError("Local preview image does not exist relative to the article JSON directory")
                    mime = mimetypes.guess_type(str(source))[0] or ""
                    if not mime.startswith("image/"):
                        raise AdapterError("Local preview image must have a recognized image extension")
                    snapshot = source.read_bytes()
                    asset_dir = self.destination.parent / (self.destination.stem + "-assets")
                    asset_dir.mkdir(parents=True, exist_ok=True)
                    name = digest(snapshot) + source.suffix.lower()
                    (asset_dir / name).write_bytes(snapshot)
                    value = urllib.parse.quote(asset_dir.name + "/" + name)
            rebuilt.append(key if value is None else key + '="' + html.escape(value, quote=True) + '"')
        self.output.append("<img " + " ".join(rebuilt) + ">")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.output.append("</" + tag + ">")

    def handle_data(self, data):
        self.output.append(data)

    def handle_entityref(self, name):
        self.output.append("&" + name + ";")

    def handle_charref(self, name):
        self.output.append("&#" + name + ";")


def preview_html(payload, destination, source_dir=None):
    validate_draft(payload)
    source_dir = Path(source_dir) if source_dir is not None else Path.cwd()
    cards = []
    for article in payload["articles"]:
        renderer = PreviewImages(source_dir, destination)
        renderer.feed(article["content"])
        renderer.close()
        cards.append("<article><h1>" + html.escape(article["title"]) + "</h1>" + "".join(renderer.output) + "</article>")
    doc = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
    doc += '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src https: http: file:; style-src \'unsafe-inline\'">'
    doc += '<title>Local article preview</title><style>body{max-width:680px;margin:32px auto;padding:0 20px;font:18px/1.7 system-ui}img{max-width:100%}article{margin-bottom:48px}</style>'
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc + "".join(cards), encoding="utf-8")


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def multipart(path):
    # Take one snapshot; its hash and uploaded bytes must describe the same asset.
    data = Path(path).read_bytes()
    if not data:
        raise AdapterError("Empty media file")
    mime = mimetypes.guess_type(str(path))[0]
    if mime not in {"image/jpeg", "image/png", "image/gif"}:
        raise AdapterError("Supported input formats: JPEG, PNG, GIF; check current endpoint limits before upload")
    # Fixed safe filename: no local path or untrusted header characters leave the machine.
    boundary = "storytelling_" + secrets.token_hex(16)
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}[mime]
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="asset{extension}"\r\nContent-Type: {mime}\r\n\r\n').encode()
    body = head + data + f"\r\n--{boundary}--\r\n".encode()
    return data, body, {"Content-Type": "multipart/form-data; boundary=" + boundary}


class WeChat:
    def __init__(self, app_id, app_secret, state_dir, transport=http_transport):
        if not app_id or not app_secret:
            raise AdapterError("Set WECHAT_APP_ID and WECHAT_APP_SECRET in the environment")
        self.app_id, self.app_secret = app_id, app_secret
        self.account = digest(app_id.encode())[:20]
        self.state = Path(state_dir) / self.account
        self.transport = transport
        self.token = None
        self.token_until = 0

    def _token(self):
        if self.token and self.token_until > time.time():
            return self.token
        value = self.transport("POST", API + "/cgi-bin/stable_token",
                               {"Content-Type": "application/json; charset=utf-8"},
                               encoded({"grant_type": "client_credential", "appid": self.app_id,
                                        "secret": self.app_secret, "force_refresh": False}))
        self._check(value)
        if not isinstance(value.get("access_token"), str) or not value["access_token"]:
            raise AdapterError("Token response did not contain an access token")
        self.token = value["access_token"]
        self.token_until = time.time() + max(0, int(value.get("expires_in", 0)) - 120)
        return self.token

    @staticmethod
    def _check(value):
        if not isinstance(value, dict):
            raise AdapterError("Unexpected API response shape")
        if value.get("errcode", 0) != 0:
            code = value.get("errcode")
            safe_code = str(code) if isinstance(code, int) else "unknown"
            raise RemoteRejected(f"WeChat API rejected the request (code {safe_code}); inspect current official documentation")

    def _request(self, operation, payload=None, media_snapshot=None):
        token = self._token()
        params = {"access_token": token}
        if media_snapshot:
            _, body, headers = media_snapshot
            if operation == "upload-cover":
                params["type"] = "image"
        else:
            body = encoded(payload)
            headers = {"Content-Type": "application/json; charset=utf-8"}
        url = API + ENDPOINTS[operation] + "?" + urllib.parse.urlencode(params)
        value = self.transport("POST", url, headers, body)
        self._check(value)
        return value

    def run(self, operation, payload=None, media_path=None, authorized=False):
        if operation not in ENDPOINTS:
            raise AdapterError("Unknown operation")
        if operation == "publish" and not authorized:
            raise AdapterError("Publish requires explicit existing human authorization for this draft")
        if operation == "draft":
            validate_draft(payload, live=True)
        if operation.startswith("upload-") and not media_path:
            raise AdapterError("A local media file is required")
        if operation in {"get-draft", "publish", "status"}:
            field = "publish_id" if operation == "status" else "media_id"
            if not isinstance(payload, dict) or set(payload) != {field} or not isinstance(payload[field], str) or not payload[field].strip():
                raise AdapterError("A nonempty remote identifier is required")
        media_snapshot = multipart(media_path) if media_path else None
        content_hash = digest(media_snapshot[0] if media_snapshot else encoded(payload))
        key = digest(encoded([operation, content_hash]))
        if operation not in MUTATIONS:
            return self._safe_result(operation, self._request(operation, payload, media_snapshot))
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt_path = self.state / (key + ".json")
        lock = self.state / (key + ".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            raise AdapterError("Operation lock exists; inspect process and remote state before recovery") from None
        try:
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                if receipt["state"] == "succeeded":
                    return {**receipt["result"], "reused_receipt": True, "operation_id": key}
                if receipt["state"] in {"pending", "unknown"}:
                    raise AdapterError("Previous outcome is unknown; inspect the platform before retrying (receipt " + key + ")")
            # Authenticate before writing pending: auth failures cannot create a duplicate post.
            self._token()
            receipt = {"version": 1, "operation": operation, "content_sha256": content_hash,
                       "created_at": time.time(), "state": "pending"}
            private_write(receipt_path, receipt)
            try:
                result = self._safe_result(operation, self._request(operation, payload, media_snapshot))
            except Exception as exc:
                receipt["state"] = "rejected" if isinstance(exc, RemoteRejected) else "unknown"
                private_write(receipt_path, receipt)
                if isinstance(exc, AdapterError):
                    raise
                raise AdapterError("Unexpected failure; outcome recorded as unknown") from None
            receipt.update(state="succeeded", result=result)
            private_write(receipt_path, receipt)
            return {**result, "operation_id": key, "reused_receipt": False}
        finally:
            lock.unlink(missing_ok=True)

    @staticmethod
    def _safe_result(operation, value):
        # Explicit allowlist, never raw responses: protects credentials even on malformed replies.
        expected = {"upload-body": "url", "upload-cover": "media_id", "draft": "media_id",
                    "publish": "publish_id", "status": "publish_status", "get-draft": "news_item"}[operation]
        if expected not in value:
            raise AdapterError("API response missing the expected result; do not assume the operation failed")
        if operation == "get-draft":
            items = value["news_item"]
            if not isinstance(items, list):
                raise AdapterError("Malformed draft response")
            # Body remains remote; return enough to verify title/count without leaking temp URLs.
            return {"state": "draft", "articles": [{"title": x.get("title", ""),
                    "content_sha256": digest(str(x.get("content", "")).encode())} for x in items]}
        if operation == "status":
            status = value["publish_status"]
            urls = [x.get("article_url") for x in value.get("article_detail", {}).get("item", [])]
            urls = [u for u in urls if isinstance(u, str) and urllib.parse.urlsplit(u).hostname == "mp.weixin.qq.com" and not any(s in u for s in ("tempkey=", "access_token="))]
            return {"state": "published" if status == 0 else "not_confirmed_published",
                    "publish_status": status, "article_urls": urls}
        result = {expected: value[expected]}
        if operation == "upload-body":
            parts = urllib.parse.urlsplit(str(value[expected]))
            if parts.scheme not in {"https", "http"} or parts.hostname != "mmbiz.qpic.cn":
                raise AdapterError("Upload returned an unexpected image URL")
        result["state"] = "submitted" if operation == "publish" else "uploaded" if operation.startswith("upload-") else "draft"
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["preview", *ENDPOINTS])
    parser.add_argument("input", help="Draft JSON file, image file, draft ID, or publish ID")
    parser.add_argument("--execute", action="store_true", help="Perform the selected remote operation")
    parser.add_argument("--authorized", action="store_true", help="Assert existing human authorization for publication of this exact draft")
    parser.add_argument("--preview-out", default="preview.html")
    parser.add_argument("--state-dir", default=str(Path.home() / ".local/state/storytelling/wechat"))
    args = parser.parse_args(argv)
    try:
        payload, media = None, None
        if args.operation in {"preview", "draft"}:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
            validate_draft(payload)
        elif args.operation.startswith("upload-"):
            media = args.input
            multipart(media)  # Validate locally even on preview.
        else:
            payload = {"publish_id" if args.operation == "status" else "media_id": args.input}
        if args.operation == "preview" or not args.execute:
            if payload and "articles" in payload:
                preview_html(payload, args.preview_out, Path(args.input).resolve().parent)
            print(json.dumps({"state": "local_preview", "operation": args.operation,
                              "network_called": False, "input_sha256": digest(Path(media).read_bytes() if media else encoded(payload))}))
            return 0
        client = WeChat(os.getenv("WECHAT_APP_ID"), os.getenv("WECHAT_APP_SECRET"), args.state_dir)
        print(json.dumps(client.run(args.operation, payload, media, args.authorized), ensure_ascii=False))
        return 0
    except (AdapterError, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, AdapterError) else "Local file or JSON error; check the supplied input"
        print(json.dumps({"state": "error", "message": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
