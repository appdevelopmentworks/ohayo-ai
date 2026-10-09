# 運用ガイド

おはようAIを動かすための初期設定と、毎日の運用・困ったときの対応をまとめます。要件は [requirements.md](requirements.md) を参照してください。

## 初期設定（最初の1回だけ）

上から順に進めます。値はすべてGitHubとCloudflareの画面で設定し、リポジトリには書きません。

公開URLは **https://ohayo-ai.aileap.workers.dev** です（workers.devのサブドメイン `aileap` は2026-10-09に登録済み。Worker `ohayo-ai` も手元からの `npx wrangler deploy` で作成済み）。

### 1. APIキーを登録する（GitHub Secrets）

GitHubのリポジトリで **Settings → Secrets and variables → Actions → Secrets** を開き、次の2つを登録します。手元の `.env` はActionsからは見えないので、ここへの登録が別に必要です。

| 名前 | 中身 |
| --- | --- |
| `GEMINI_API_KEY` | Google AI StudioのAPIキー（メイン。決済の登録なしの無料枠で動作確認済み） |
| `GROQ_API_KEY` | GroqのAPIキー（予備。なくても動くが、Geminiが止まった日に記事が作れない） |

### 2. 公開URLを登録する（GitHub Variables）

同じ画面の **Variables** タブに次を登録します。秘密の値ではありません（ページのHTMLにそのまま出ます）。最初の実行より前に入れておくと、最初のページから共有用の画像（OGP）のタグが入ります。

| 名前 | 中身 | 使い道 |
| --- | --- | --- |
| `SITE_URL` | `https://ohayo-ai.aileap.workers.dev`（最後の `/` なし） | XやLINEで共有したときの画像（OGP）と正式URL。未設定だとこれらのタグを出さない |

### 3. 最初のニュースを作る（手動実行）

**Actions → update-news → Run workflow** を押します（`dry_run` はオフのまま）。数分〜15分ほどで終わり（Groqに切り替わった日は長くなる）、`Update news for YYYY-MM-DD` というコミットが増えれば成功です。`public/` にページができます。

### 4. 毎朝の自動公開をつなぐ（Workers Builds）

必ず3の後に行います。先につなぐと、まだ空の `public/` で公開中のページが上書きされます。

1. Cloudflareのダッシュボードで **Workers & Pages → ohayo-ai → Settings → Builds → Connect** を選び、GitHubと連携して `ohayo-ai` リポジトリを選ぶ（Workerはもうあるので「リポジトリをインポート」は使わない）
2. 設定はこのとおりにする
   - 本番ブランチ: `main`
   - ビルドコマンド: 空欄
   - デプロイコマンド: `npx wrangler deploy`
   - ルートディレクトリ: `/`
3. 保存後、最新のコミットでデプロイが走る。https://ohayo-ai.aileap.workers.dev が本物のニュースになっていれば完了

これ以降は、毎朝のコミットのたびに自動で公開されます。Worker名は `wrangler.jsonc` の `name`（`ohayo-ai`）と同じでないとビルドが失敗します。

### 5. 閲覧数の計測（任意、Cloudflare Web Analytics）

1. Cloudflareの **Web Analytics → サイトを追加** でホスト名 `ohayo-ai.aileap.workers.dev` を登録する
2. 表示されるJSスニペットの `"token": "..."` の部分（英数字32文字）をコピーする。スニペット自体を貼る必要はない
3. GitHubの **Variables** に `CF_WEB_ANALYTICS_TOKEN` として登録する

設定は次のページ生成から反映されます。すぐ反映したいときは、もう一度 **Run workflow** を押します。

### 手元からの公開（Workers Buildsをつなぐ前の確認用）

見本のページをCloudflareで確かめたいときは、手元から直接公開できます（要Node.js、初回は `npx wrangler login`）。Workers Buildsをつないだ後は、次のpushで上書きされます。

```bash
uv run ai-news --dry-run
npx wrangler deploy
```

## 毎日の動き

- 毎朝 6:17（JST）に `update-news` が動き、7時ごろまでにページが新しくなる
- 変更があれば `data/` と `public/` をコミットし、それをきっかけにCloudflareが公開する
- 失敗しても、取得状況（`data/source_health.json` など）はコミットしてから赤い失敗にする。GitHubから失敗のメールが届く
- コードを変更してpushすると `ci` がテストを動かす（毎朝の更新では動かない）

## 失敗のメールが来たら

Actionsの該当の実行を開き、**Run pipeline** のログの最後の行を見ます。

| ログの内容 | 意味 | 対応 |
| --- | --- | --- |
| `no items for 2 days in a row from: anthropic` など | そのソースが2日続けて0件。サイトの作りが変わった可能性が高い | そのソースのページやフィードを確認し、`src/ai_news/sources/` の取得処理を直す。ほかのソースのニュースは普段どおり公開されている |
| `no edition made: ranking failed` | GeminiとGroqの両方で選別に失敗した。その日のページは前日のまま | APIキーの期限や無料枠の上限を確認し、Run workflowでやり直す（同じ日のやり直しは何度でもできる） |
| `no LLM API key` | Secretsにキーがない | 初期設定の1を確認する |

同じ日に何度やり直しても、その日に一度見た記事が「既読」扱いで消えることはありません。

## 手元での確認

```bash
uv sync
uv run pytest
uv run ai-news --dry-run
uv run python -m http.server 8000 --directory public
```

`--dry-run` は記録済みのデータ（`tests/fixtures/`）だけで最後まで動き、`public/` に見本のページを作ります。この `public/` はコミットしないでください（翌朝の実行で上書きされますが、それまで見本が公開されてしまいます）。戻すときは `git checkout -- public && git clean -fd public` を使います。

## 費用について

すべて無料枠で動きます（GitHub Actions、Cloudflare Workersの静的配信とWorkers Builds、Gemini API、Groq、Web Analytics）。有料のサービスや、有料プランが必要な機能は追加しないでください。
