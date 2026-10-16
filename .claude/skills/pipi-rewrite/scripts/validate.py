#!/usr/bin/env python3
"""ADVENTURE PiPi リライト用HTMLの自動検証。

使い方:
  python3 validate.py OUTPUT.html --island ishigaki [--original CURRENT.html] [--strict-links]

終了コード: ERROR が1件でもあれば 1、なければ 0。
"""
import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).resolve().parent.parent
ISLANDS = ("ishigaki", "miyako", "iriomote")

BANNED_NEW_TAGS = ("img", "iframe", "script", "h1", "h4", "ul", "ol", "li")
BANNED_STRINGS = (
    "contentReference", "oaicite", "data-mce-fragment", "data-mce-src",
    "data-mce-href", "data-mce-style", "data-mce-bogus", "contenteditable",
    "spellcheck", "data-gramm", "data-enable-grammarly",
    "Apple-interchange-newline", "MsoNormal", "<o:p>", 'lang="ja-JP"',
)
QA_NAME_STYLE = "font-size: 16px;"
QA_ANSWER_STYLE = "font-weight: 400; font-size: 16px;"


def load_island(key):
    return json.loads((SKILL_DIR / "islands" / f"{key}.json").read_text(encoding="utf-8"))


class Scanner(HTMLParser):
    """タグ数・見出し順・リンク・divの対応・FAQ構造を集める。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag_counts = {}
        self.headings = []          # (tag, text, index_in_stream)
        self.stream = []            # 開始タグ・テキストの並び（h2直下のh3判定用）
        self.links = []
        self.div_stack = []         # 各divが FAQ wrap に属するか
        self.div_errors = []
        self.qa_blocks = []         # 各FAQの {name, answer_spans, ...}
        self._qa_depth = None
        self._cur_heading = None
        self._span_ctx = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag in ("h2", "h3"):
            self._cur_heading = [tag, ""]
        if tag not in ("br", "strong", "span", "a"):
            self.stream.append(("tag", tag))
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "div":
            cls = a.get("class") or ""
            self.div_stack.append(cls)
            if "ttsd_qa-wrap" in cls:
                if self._qa_depth is not None:
                    self.div_errors.append("FAQブロックの中に別のFAQブロックが始まっています（閉じ忘れ）")
                self._qa_depth = len(self.div_stack)
                self.qa_blocks.append({
                    "ok_wrap": a.get("itemtype") == "https://schema.org/Question"
                               and a.get("itemprop") == "mainEntity",
                    "has_name": False, "has_answer": False, "has_text": False,
                    "name": "", "answer_spans": 0, "bad_styles": [],
                })
            elif self._qa_depth is not None:
                q = self.qa_blocks[-1]
                if a.get("itemprop") == "name":
                    q["has_name"] = True
                if a.get("itemprop") == "acceptedAnswer" and a.get("itemtype") == "https://schema.org/Answer":
                    q["has_answer"] = True
                if a.get("itemprop") == "text":
                    q["has_text"] = True
        if tag == "span":
            ctx = None
            if self._qa_depth is not None:
                parent = self.div_stack[-1] if self.div_stack else ""
                q = self.qa_blocks[-1]
                style = (a.get("style") or "").strip()
                if "ttsd_qa-summary" in parent:
                    ctx = "name"
                    if style != QA_NAME_STYLE:
                        q["bad_styles"].append(f"質問span style=\"{style}\"")
                elif q["has_text"]:
                    ctx = "answer"
                    q["answer_spans"] += 1
                    if style != QA_ANSWER_STYLE:
                        q["bad_styles"].append(f"回答span style=\"{style}\"")
            self._span_ctx.append(ctx)

    def handle_endtag(self, tag):
        if tag in ("h2", "h3") and self._cur_heading:
            self.headings.append((self._cur_heading[0], self._cur_heading[1].strip(), len(self.stream)))
            self._cur_heading = None
        if tag == "span" and self._span_ctx:
            self._span_ctx.pop()
        if tag == "div":
            if not self.div_stack:
                self.div_errors.append("対応する開始タグのない </div> があります")
                return
            if self._qa_depth is not None and len(self.div_stack) == self._qa_depth:
                self._qa_depth = None
            self.div_stack.pop()

    def handle_data(self, data):
        if self._cur_heading is not None:
            self._cur_heading[1] += data
        if data.strip():
            self.stream.append(("text", data.strip()))
            if self._span_ctx and self._span_ctx[-1] == "name" and self.qa_blocks:
                self.qa_blocks[-1]["name"] += data.strip()


def visible_chars(html):
    text = re.sub(r"\[/?su_[^\]]*\]", "", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;|\s", "", text)
    return len(text)


def shortcodes(html):
    return re.findall(r"\[su_[a-z_]+[^\]]*\]", html)


def img_srcs(html):
    return re.findall(r'<img[^>]*\ssrc="([^"]+)"', html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--island", required=True, choices=ISLANDS)
    ap.add_argument("--original", help="現行記事のWP本文HTML（既存要素の保持チェック用）")
    ap.add_argument("--strict-links", action="store_true",
                    help="島jsonに無い自ドメインURLを ERROR にする（既定は WARN）")
    args = ap.parse_args()

    html = Path(args.html).read_text(encoding="utf-8")
    original = Path(args.original).read_text(encoding="utf-8") if args.original else None
    island = load_island(args.island)
    others = [load_island(k) for k in ISLANDS if k != args.island]

    errors, warns, infos = [], [], []

    sc = Scanner()
    sc.feed(html)
    sc.close()
    orig_counts = {}
    if original:
        osc = Scanner()
        osc.feed(original)
        orig_counts = osc.tag_counts

    # 1. 新規禁止タグ
    for t in BANNED_NEW_TAGS:
        n, base = sc.tag_counts.get(t, 0), orig_counts.get(t, 0)
        if n > base:
            errors.append(f"<{t}> が {n} 個あります（現行記事は {base} 個）。新しく作れないタグです")

    # 2. 禁止文字列
    for s in BANNED_STRINGS:
        if s in html:
            errors.append(f"禁止コード「{s}」が含まれています")

    # 3. 空段落
    if re.search(r"<p>\s*</p>", html):
        errors.append("空の <p></p> があります（余白は <p>&nbsp;</p>）")

    # 4. divの対応・FAQ構造
    errors.extend(sc.div_errors)
    if sc.div_stack:
        errors.append(f"閉じられていない <div> が {len(sc.div_stack)} 個あります")
    for i, q in enumerate(sc.qa_blocks, 1):
        label = f"FAQ{i}「{q['name'][:20] or '（質問なし）'}」"
        if not q["ok_wrap"]:
            errors.append(f"{label}: wrap の itemprop/itemtype が違います")
        if not q["has_name"] or not q["name"]:
            errors.append(f"{label}: itemprop=\"name\" の質問がありません")
        if not (q["has_answer"] and q["has_text"]):
            errors.append(f"{label}: acceptedAnswer / itemprop=\"text\" がありません")
        if q["answer_spans"] == 0:
            errors.append(f"{label}: 回答の <span> がありません")
        elif q["answer_spans"] > 2:
            warns.append(f"{label}: 回答が {q['answer_spans']} 文あります（原則2文まで）")
        for b in q["bad_styles"]:
            errors.append(f"{label}: {b} はテンプレートと違います")
    if not sc.qa_blocks:
        warns.append("FAQ（ttsd_qa-wrap）がありません")

    # 5. あいさつ文・最後のH2
    if island["greeting"].replace("<br>", "") not in html:
        errors.append("冒頭の固定あいさつ文がありません（島jsonの greeting をそのまま貼る）")
    elif html.find(island["greeting"].split("</p>")[0]) > html.find("<h2"):
        warns.append("固定あいさつ文が最初のH2より後ろにあります")
    h2s = [h for h in sc.headings if h[0] == "h2"]
    if not h2s or h2s[-1][1] != "さいごに":
        errors.append("最後のH2が「さいごに」ではありません")
    if island["activity_url"] not in html:
        warns.append("アクティビティ一覧CTA（activity_url）がありません")

    # 6. H2直後にH3
    for idx, (tag, text, pos) in enumerate(sc.headings):
        if tag == "h2" and pos < len(sc.stream):
            nxt = sc.stream[pos]
            if nxt == ("tag", "h3"):
                errors.append(f"H2「{text}」の直後にH3があります（要約段落を入れる）")
    if sc.headings and sc.headings[0][0] == "h3":
        errors.append("最初の見出しがH3です（H2から始める）")

    # 7. 島の混在
    for o in others:
        if o["domain"] in html:
            errors.append(f"他島のドメイン {o['domain']} が含まれています")
        if o["brand_color"].lower() in html.lower():
            errors.append(f"他島のブランドカラー {o['brand_color']}（{o['name']}）が含まれています")
        if o["name"] in re.sub(r"<[^>]+>", "", html):
            warns.append(f"本文に「{o['name']}」が出てきます。他島の情報が混ざっていないか確認してください")
    for m in re.finditer(r'\[su_(?:button|box)[^\]]*?(?:background|box_color|title_color)="(#[0-9a-fA-F]{3,6})"', html):
        if m.group(1).lower() != island["brand_color"].lower():
            errors.append(f"ショートコードの色 {m.group(1)} がブランドカラー {island['brand_color']} と違います")

    # 8. リンク
    known = {island["activity_url"]}
    known |= {t.get("url") for t in island.get("tours", []) if t.get("url")}
    known |= {c.get("url") for c in island.get("columns", []) if c.get("url")}
    orig_links = set(re.findall(r'href="([^"]+)"', original)) if original else set()
    sc_urls = re.findall(r'\[su_button[^\]]*\surl="([^"]+)"', html)
    for url in sc.links + sc_urls:
        host = urlparse(url).netloc
        if host.endswith(island["domain"]):
            if url not in known and url not in orig_links:
                msg = f"島jsonにも現行記事にも無いURL: {url}（推測URLの可能性）"
                (errors if args.strict_links else warns).append(msg)
        elif host and not any(host.endswith(o["domain"]) for o in others):
            infos.append(f"外部リンク: {url}")

    # 9. 現行記事の要素が消えていないか
    if original:
        out_sc = set(shortcodes(html))
        for s in shortcodes(original):
            if s not in out_sc:
                warns.append(f"現行記事のショートコードが消えています: {s[:80]}")
        for src in img_srcs(original):
            if src not in html:
                warns.append(f"現行記事の画像が消えています: {src}")
        for href in orig_links:
            if href not in html:
                warns.append(f"現行記事のリンクが消えています: {href}")

    # 10. 文字数
    n = visible_chars(html)
    infos.append(f"本文文字数（タグ除く）: {n}字")
    if n < 3000:
        warns.append(f"本文が {n} 字です（目安 3,000〜5,000字）")
    elif n > 6000:
        warns.append(f"本文が {n} 字です（目安 3,000〜5,000字。水増しがないか確認）")
    infos.append(f"H2: {len(h2s)} 個 / H3: {sum(1 for h in sc.headings if h[0] == 'h3')} 個 / FAQ: {len(sc.qa_blocks)} 問")

    for label, items in (("ERROR", errors), ("WARN", warns), ("INFO", infos)):
        for it in items:
            print(f"[{label}] {it}")
    print(f"\n結果: ERROR {len(errors)} / WARN {len(warns)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
