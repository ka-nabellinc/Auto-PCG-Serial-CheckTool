"""撮影画像の一覧取得（S3）とダウンロード。"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

_UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I
)


def _parse_keys_and_token(data: bytes):
    """S3 ListObjectsV2 のXMLから (キー一覧, NextContinuationToken) を返す。名前空間は無視。"""
    root = ET.fromstring(data)
    keys: List[str] = []
    token = None
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "Key" and el.text:
            keys.append(el.text.strip())
        elif tag == "NextContinuationToken" and el.text:
            token = el.text.strip()
    return keys, token


def list_scan_keys(s3_list_url: str) -> List[str]:
    """S3のListObjectsV2(XML)を叩き、registrations/{id}/... のキー一覧を返す（認証不要）。
    1000件超でも NextContinuationToken を辿って全件取得する。"""
    keys: List[str] = []
    token = None
    for _ in range(50):  # 最大50ページ（5万件）
        url = s3_list_url
        if token:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}continuation-token={urllib.parse.quote(token, safe='')}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        page_keys, token = _parse_keys_and_token(data)
        keys.extend(page_keys)
        if not token:
            break
    return keys


def map_kanri_id_to_url(keys: List[str], image_base_url: str) -> Dict[str, str]:
    """キー一覧から {管理ID(UUID): 画像URL} を作る。ファイル名 {ts}_{uuid}.png を前提。"""
    out: Dict[str, str] = {}
    for k in keys:
        m = _UUID_RE.search(k)
        if m:
            out[m.group(1).lower()] = image_base_url.format(key=k)
    return out


def download_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tcg-linker/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()
