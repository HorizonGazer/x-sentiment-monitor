# Architecture & Internal Design

## Data Flow

```
Firefox cookies.sqlite
        │
        ▼
  Extract & filter (.x.com / .twitter.com)
        │
        ▼
  Playwright Chromium (headless)
        │
        ├─► Search page: x.com/search?q={keyword}&f=live
        │       │
        │       ▼
        │   Scroll + parse <article> nodes
        │       │
        │       ▼
        │   List[TweetInfo] (up to --tweets)
        │
        ├─► For each tweet: detail page
        │       │
        │       ▼
        │   Parse reply <article> nodes
        │       │
        │       ▼
        │   Sort by favorite_count → top N
        │
        ▼
  Sentiment Analysis (word frequency)
        │
        ▼
  Draft Generation (3 templates)
        │
        ▼
  Save: report.md + raw.json + run.log
```

## Cookie Extraction

Source: Firefox `cookies.sqlite` (SQLite3, locked while Firefox runs).

1. Copy `cookies.sqlite` to temp file (avoids lock conflicts)
2. Query `moz_cookies` for `.x.com` and `.twitter.com` domains
3. Prefer `.x.com` cookies over `.twitter.com`
4. Validate `auth_token` + `ct0` exist
5. Inject into Playwright context via `context.add_cookies()`

## DOM Selectors

Tweet data extracted via `element.evaluate()` JavaScript:

| Field | Selector / Method |
|---|---|
| Author | `[data-testid="User-Name"] a[href^="/"]` → text starting with `@` |
| Content | `[data-testid="tweetText"]` → `.innerText` |
| Time | `time` → `datetime` attribute |
| Replies | `[data-testid="reply"]` → `aria-label` (e.g. "5 Replies. Reply") |
| Reposts | `[data-testid="retweet"]` → `aria-label` |
| Likes | `[data-testid="like"]` → `aria-label` |
| URL | `a[href*="/status/"]` → `.href` |

### Stat Parsing

Aria labels follow: `"{count} {ActionWord}. {Action}"`.
Examples: `"42 Likes. Like"`, `"1.2K reposts. Repost"`

`parse_stat()` extracts the number with K/M/B suffix support.

## Data Models

```python
@dataclass
class ReplyInfo:
    author: str       # screen_name without @
    likes: int
    reposts: int
    replies: int
    created_at: str   # ISO 8601
    tags: list[str]   # hashtags
    content: str      # normalized text
    url: str          # full tweet URL

@dataclass
class TweetInfo:      # same fields plus:
    tweet_id: str
    top_replies: list[ReplyInfo]
```

## Scroll Collection Strategy

`collect_search_tweets()`:
1. Wait 2.5s for DOM
2. Parse visible `<article>` elements
3. Deduplicate by `tweet_id`
4. Scroll 3000px
5. Stop at `limit` or 6 consecutive no-new-tweet rounds

`collect_replies()`: same pattern, 5 stable rounds cutoff.

## Sentiment Analysis

1. Concatenate all tweet + reply texts
2. Count bullish/bearish word occurrences
3. Classify: bullish > bearish×1.2 → "偏多", bearish > bullish×1.2 → "偏空", else → "多空分歧"

Topic detection:
1. Match `HOT_TOPICS` against text
2. Count hashtag frequency
3. Tokenize + count words (minus stop words)
4. Merge + deduplicate → top 8

## Output Files

| File | Format | Contents |
|---|---|---|
| `*_report.md` | Markdown | Summary → ranked tweets with replies → 3 drafts |
| `*_raw.json` | JSON | Full structured data: summary + tweets + drafts |
| `*_run.log` | Text | Run metadata: keyword, counts, paths, sentiment |
