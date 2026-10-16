# WordPress HTMLルール（validate.py が自動でチェックする）

## 使ってよいもの
- `<p>` `<br>` `<strong>` `<span>` `<a>` `<h2>` `<h3>`
- `[su_button]` `[su_box]` `[su_table]`
- 比較表・施設情報・FAQの中だけ：`<table>` `<tbody>` `<tr>` `<td>` `<div>`

## 新しく作らないもの
`<img>` `<iframe>` `<script>` `<h1>` `<h4>` `<ul>` `<ol>` `<li>`
（現行記事にあったものは、同じ数まで残してよい）

## 段落の形
- 基本は `<p>文章。</p><br>`
- 空の `<p></p>` は使わない。余白が必要なときだけ `<p>&nbsp;</p>`。

## 入れてはいけない文字列
contentReference / oaicite / data-mce-fragment / data-mce-src / data-mce-href / data-mce-style / data-mce-bogus / contenteditable / spellcheck / data-gramm / data-gramm_editor / data-enable-grammarly / Apple-interchange-newline / MsoNormal / `<o:p>` / lang="ja-JP"

## 島の混在
- 他島のドメイン・ブランドカラーを入れない。
- `[su_button]` `[su_box]` の色は対象島のブランドカラーだけ。
