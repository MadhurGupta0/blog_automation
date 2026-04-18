import sys
import re
import random
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
import boto3
from supabase import create_client, Client
import os

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# ── AWS Bedrock ───────────────────────────────────────────────────────────────

bedrock_client = boto3.client(
    "bedrock-runtime",
    region_name="us-east-1",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

MODEL_ID = "meta.llama3-8b-instruct-v1:0"

# ── WordPress ─────────────────────────────────────────────────────────────────

WP_URL          = "https://blogs.melloai.health/wp-json/wp/v2/posts"
WP_MEDIA_URL    = "https://blogs.melloai.health/wp-json/wp/v2/media"
WP_CATEGORY_URL = "https://blogs.melloai.health/wp-json/wp/v2/categories"
WP_USERNAME     = "melloai"
WP_PASSWORD     = os.getenv("app_password")

_category_cache: dict[str, int] = {}

def get_or_create_category(name: str) -> int:
    """Return the WordPress category ID for *name*, creating it if needed."""
    if name in _category_cache:
        return _category_cache[name]
    auth = HTTPBasicAuth(WP_USERNAME, WP_PASSWORD)
    # Search existing
    resp = requests.get(WP_CATEGORY_URL, params={"search": name, "per_page": 5}, auth=auth)
    for cat in resp.json():
        if cat["name"].lower() == name.lower():
            _category_cache[name] = cat["id"]
            return cat["id"]
    # Create if not found
    resp = requests.post(WP_CATEGORY_URL, auth=auth, json={"name": name})
    resp.raise_for_status()
    cat_id = resp.json()["id"]
    _category_cache[name] = cat_id
    return cat_id

# ── Pexels ────────────────────────────────────────────────────────────────────

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# ── Supabase ──────────────────────────────────────────────────────────────────

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

BLOG_TABLE  = "blog_automation"
QUIZ_TABLE  = "blog_automation"
SITE_BASE   = "https://melloai.health"

FALLBACK_QUIZ_LINKS = [
    {"title": "Emotional Intelligence Quiz",  "url": "https://melloai.health/quiz/emotional-intelligence"},
    {"title": "Attachment Style Quiz",        "url": "https://melloai.health/quiz/attachment-style"},
    {"title": "Stress Personality Quiz",      "url": "https://melloai.health/quiz/stress-personality"},
    {"title": "Self-Care Quiz",               "url": "https://melloai.health/quiz/self-care"},
]


def is_topic_used(title: str) -> bool:
    """Return True if a blog with this title already exists in Supabase."""
    resp = (
        supabase.table(BLOG_TABLE)
        .select("id")
        .ilike("topic", title.strip())
        .limit(1)
        .execute()
    )
    return len(resp.data) > 0


def get_existing_blog_links() -> list[dict]:
    """
    Fetch all published blogs from Supabase.
    Returns list of {"topic": ..., "url": ...} dicts.
    """
    resp = (
        supabase.table(BLOG_TABLE)
        .select("topic, url")
        .not_.is_("url", "null")
        .execute()
    )
    return [row for row in resp.data if row.get("url")]


def get_quiz_links() -> list[dict]:
    """
    Fetch all quizzes from Supabase.
    Returns list of {"title": ..., "url": ...} dicts.
    Falls back to empty list if the table doesn't exist yet.
    """
    try:
        resp = (
            supabase.table(QUIZ_TABLE)
            .select("topic, url")
            .not_.is_("url", "null")
            .execute()
        )
        return [{"title": row["topic"], "url": row["url"]} for row in resp.data if row.get("url")]
    except Exception as e:
        print(f"  Warning: could not fetch quizzes from Supabase — {e}")
        return []


def push_to_supabase(topic: str, brief: dict, slug: str) -> None:
    """Insert a completed blog record into Supabase."""
    public_url = f"{SITE_BASE}/blogs/{slug}" if slug else ""
    supabase.table(BLOG_TABLE).insert({
        "topic":     topic,
        "details":   brief,
        "completed": True,
        "url":       public_url,
    }).execute()
    print(f"  Saved to Supabase: '{topic}' → {public_url}")


# ── Mid-content injection ─────────────────────────────────────────────────────

def inject_mid_content_blocks(
    content: str,
    blog_links: list[dict],
    quiz_links: list[dict],
) -> str:
    """
    Split the AI-generated HTML on <h2> boundaries and inject:
      - After section 1 → a styled "Related Read" blog callout
      - After section 3 → a styled "Take the Quiz" callout
      - After section 5 → another "You might also like" blog callout
    Then guarantee a strong CTA block (with quiz button) at the very end.
    """
    # Shuffle so each post gets a different selection
    blog_pool = list(blog_links)
    quiz_pool = list(quiz_links)
    random.shuffle(blog_pool)
    random.shuffle(quiz_pool)

    # Split content keeping each <h2…> tag at the start of its chunk
    parts = re.split(r'(?=<h2[\s>])', content, flags=re.IGNORECASE)

    result = [parts[0]]  # intro paragraph(s) before the first H2
    blog_idx = 0
    quiz_idx = 0

    for section_num, part in enumerate(parts[1:], start=1):
        result.append(part)

        # ── After section 1 → related blog ───────────────────────────────────
        if section_num == 1 and blog_pool:
            link = blog_pool[blog_idx % len(blog_pool)]
            blog_idx += 1
            result.append(
                '\n<div class="related-read" '
                'style="background:#f0f7ff;border-left:4px solid #3a7bd5;'
                'padding:12px 16px;margin:24px 0;border-radius:4px;">'
                '<p style="margin:0;">📖 <strong>Related Read:</strong>&nbsp;'
                f'<a href="{link["url"]}" title="{link.get("topic","")}">'
                f'{link.get("topic", "Read more")}</a></p>'
                '</div>\n'
            )

        # ── After section 3 → quiz callout ───────────────────────────────────
        elif section_num == 3 and quiz_pool:
            link = quiz_pool[quiz_idx % len(quiz_pool)]
            quiz_idx += 1
            result.append(
                '\n<div class="quiz-callout" '
                'style="background:#fff8e1;border-left:4px solid #f9a825;'
                'padding:12px 16px;margin:24px 0;border-radius:4px;">'
                '<p style="margin:0;">🧠 <strong>Think you know this topic?</strong>&nbsp;'
                f'<a href="{link["url"]}" title="{link.get("title","Quiz")}" '
                f'style="font-weight:bold;">{link.get("title", "Take the Quiz")} →</a></p>'
                '</div>\n'
            )

        # ── After section 5 → second related blog ────────────────────────────
        elif section_num == 5 and blog_pool:
            link = blog_pool[blog_idx % len(blog_pool)]
            blog_idx += 1
            result.append(
                '\n<div class="related-read" '
                'style="background:#f0f7ff;border-left:4px solid #3a7bd5;'
                'padding:12px 16px;margin:24px 0;border-radius:4px;">'
                '<p style="margin:0;">📖 <strong>You might also like:</strong>&nbsp;'
                f'<a href="{link["url"]}" title="{link.get("topic","")}">'
                f'{link.get("topic", "Read more")}</a></p>'
                '</div>\n'
            )

    combined = "".join(result)

    # ── Guarantee a strong end CTA (always from FALLBACK_QUIZ_LINKS) ─────────
    q = random.choice(FALLBACK_QUIZ_LINKS)
    quiz_button = (
        f'<p style="margin-bottom:0;">'
        f'<a href="{q["url"]}" '
        f'style="display:inline-block;background:#3a7bd5;color:#fff;'
        f'padding:12px 28px;border-radius:6px;text-decoration:none;'
        f'font-weight:bold;font-size:1rem;">'
        f'{q["title"]} →</a></p>'
    )

    if '<div class="cta-block">' not in combined:
        # AI didn't write one — append ours
        combined += (
            '\n<div class="cta-block" '
            'style="background:#e8f5e9;border-radius:8px;padding:28px 24px;'
            'margin:36px 0;text-align:center;">'
            '<h3 style="margin-top:0;">Ready to Take the Next Step?</h3>'
            '<p>Your mental wellness journey starts with one small action. '
            'Explore our resources, read more, or test yourself with a quick quiz.</p>'
            f'{quiz_button}'
            '</div>\n'
        )
    else:
        # AI wrote a CTA — inject the quiz button inside it before closing tag
        if quiz_button and quiz_button not in combined:
            combined = combined.replace(
                '</div>',
                f'{quiz_button}</div>',
                1,  # only the first occurrence after the CTA block
            )
            # More precise: replace inside the cta-block specifically
            combined = re.sub(
                r'(<div class="cta-block"[^>]*>)(.*?)(</div>)',
                lambda m: m.group(1) + m.group(2) + quiz_button + m.group(3),
                combined,
                count=1,
                flags=re.DOTALL,
            )

    return combined


# ── Blog generation ───────────────────────────────────────────────────────────

def _build_outline_text(outline: dict) -> str:
    lines = [f"Introduction: {outline.get('introduction', '')}"]
    for sec in outline.get("sections", []):
        lines.append(f"H2: {sec['h2']}")
        for h3 in sec.get("h3s", []):
            lines.append(f"  H3: {h3}")
    lines.append(f"Conclusion: {outline.get('conclusion', '')}")
    return "\n".join(lines)


def generate_blog(
    brief: dict,
    blog_links: list[dict] = None,
    quiz_links: list[dict] = None,
) -> tuple[str, str]:
    """Generate SEO-optimised blog HTML from a full SEO brief dict."""
    title              = brief["title"]
    focus_keyword      = brief["focus_keyword"]
    secondary_keywords = ", ".join(brief["secondary_keywords"])
    word_count         = brief["suggested_word_count"]
    meta_description   = brief["meta_description"]
    snippet_target     = brief["featured_snippet_target"]
    search_intent      = brief["search_intent"]
    outline_text       = _build_outline_text(brief["content_outline"])

    # Build optional inline-linking hint for the AI
    blog_links_hint = ""
    if blog_links:
        sample = blog_links[:8]
        entries = "\n".join(
            f'- <a href="{b["url"]}">{b.get("topic", b["url"])}</a>'
            for b in sample
        )
        blog_links_hint = f"""
EXISTING BLOG POSTS — weave 1-2 natural in-text hyperlinks to these where the topic fits:
{entries}
"""

    quiz_links_hint = ""
    if quiz_links:
        sample = quiz_links[:4]
        entries = "\n".join(
            f'- <a href="{q["url"]}">{q.get("title", q["url"])}</a>'
            for q in sample
        )
        quiz_links_hint = f"""
QUIZZES — mention and link to 1 relevant quiz naturally in the body copy:
{entries}
"""

    prompt = f"""You are a professional health and wellness blog writer.
Write an SEO-optimised blog post in HTML format suitable for WordPress.

BRIEF:
- Title: {title}
- Focus Keyword: {focus_keyword}
- Secondary Keywords: {secondary_keywords}
- Search Intent: {search_intent}
- Target Word Count: {word_count}
- Meta Description (for context only, do NOT output it): {meta_description}
- Featured Snippet Target (answer this clearly and concisely in the post): {snippet_target}

CONTENT OUTLINE — follow this structure exactly:
{outline_text}
{blog_links_hint}{quiz_links_hint}
RULES:
1. ORIGINALITY: Write entirely from your own knowledge. Do NOT copy or paraphrase external sources.
2. INTRO: The first paragraph must NOT contain the focus keyword — hook the reader with a relatable scenario, question, or surprising fact.
3. KEYWORD DENSITY: Focus keyword at or below 2% density. Weave secondary keywords naturally throughout.
4. FEATURED SNIPPET: Include a concise 2-3 sentence direct answer to "{snippet_target}" under its own <h2>.
5. FORMAT: Use <h2> for H2 headings, <h3> for H3 subheadings, <p> for paragraphs, <ul>/<li> for lists.
6. CTA: End with a clear Call-To-Action inside <div class="cta-block"> — encourage readers to explore, reflect, or take a quiz.
7. WORD COUNT: Stay within {word_count}.

Output ONLY the HTML content body — no <html>, <head>, or <body> tags. Do not include the title in the output. Do NOT add a word count, note, summary, or any text after the closing HTML tag.
"""

    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=[
            {"role": "user", "content": [{"text": "You are an expert SEO blog writer for a mental health platform.\n\n" + prompt}]},
        ],
        inferenceConfig={"maxTokens": 2048, "temperature": 0.7, "topP": 0.9},
        additionalModelRequestFields={},
        performanceConfig={"latency": "standard"},
    )

    content = response["output"]["message"]["content"][0]["text"].strip()

    # Llama3 often appends a word-count note after the HTML — remove it
    content = re.sub(r'\n*\*?\*?Word\s*[Cc]ount[:\s*\d,words.*]*$', '', content, flags=re.IGNORECASE).strip()
    content = re.sub(r'\n*\(?\d[\d,]+\s*words?\)?\.?\s*$', '', content, flags=re.IGNORECASE).strip()

    # Inject mid-content callout boxes and guarantee end CTA
    content = inject_mid_content_blocks(content, blog_links or [], quiz_links or [])

    return title, content


# ── Image helpers ─────────────────────────────────────────────────────────────

_ILLUSTRATION_KEYWORDS = {
    "illustration", "concept art", "clipart", "clip art", "drawing",
    "cartoon", "vector", "artwork", "digital art", "sketch", "animation",
    "3d render", "render", "graphic", "icon",
}

def _looks_like_illustration(photo: dict) -> bool:
    text = (photo.get("alt") or "").lower()
    return any(kw in text for kw in _ILLUSTRATION_KEYWORDS)

def search_image(query: str) -> tuple[bytes, str, str]:
    if not PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY is not set in .env")

    resp = requests.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": 15, "orientation": "landscape"},
        headers={"Authorization": PEXELS_API_KEY},
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])

    if not photos:
        raise ValueError(f"No images found on Pexels for: {query}")

    # Prefer real photos over illustrations/concept art
    real_photos = [p for p in photos if not _looks_like_illustration(p)]
    photo = real_photos[0] if real_photos else photos[0]

    image_url = photo["src"]["large2x"]
    alt_text  = photo.get("alt") or query
    filename  = f"{query.replace(' ', '_')[:50]}.jpg"

    print(f"  Image by {photo['photographer']} on Pexels")
    return requests.get(image_url).content, filename, alt_text


def upload_image_to_wordpress(image_bytes: bytes, filename: str, alt_text: str) -> int:
    resp = requests.post(
        WP_MEDIA_URL,
        auth=HTTPBasicAuth(WP_USERNAME, WP_PASSWORD),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg",
        },
        data=image_bytes,
    )
    resp.raise_for_status()
    media_id = resp.json()["id"]

    requests.post(
        f"{WP_MEDIA_URL}/{media_id}",
        auth=HTTPBasicAuth(WP_USERNAME, WP_PASSWORD),
        json={"alt_text": alt_text},
    )

    print(f"  Uploaded image, media ID: {media_id}")
    return media_id


# ── WordPress publish ─────────────────────────────────────────────────────────

def publish_blog(title: str, content: str, brief: dict, featured_media_id: int = None) -> dict:
    # Build category list: always "Mental Health" + focus keyword category
    category_names = ["Mental Health"]
    if brief.get("focus_keyword"):
        category_names.append(brief["focus_keyword"].title())
    category_ids = [get_or_create_category(n) for n in category_names]

    data = {
        "title":      title,
        "content":    content,
        "status":     "publish",
        "slug":       brief.get("url_slug", ""),
        "excerpt":    brief.get("meta_description", ""),
        "categories": category_ids,
    }
    if featured_media_id:
        data["featured_media"] = featured_media_id

    resp = requests.post(
        WP_URL,
        auth=HTTPBasicAuth(WP_USERNAME, WP_PASSWORD),
        json=data,
    )
    resp.raise_for_status()
    return resp.json()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from seotrends import get_seo_topics

    print("Fetching existing blog links from Supabase...")
    blog_links = get_existing_blog_links()
    print(f"  Found {len(blog_links)} published blogs.")

    print("Fetching quiz links from Supabase...")
    quiz_links = get_quiz_links()
    # Always include fallback quiz links; deduplicate by URL
    existing_urls = {q["url"] for q in quiz_links}
    quiz_links += [q for q in FALLBACK_QUIZ_LINKS if q["url"] not in existing_urls]
    print(f"  Found {len(quiz_links)} quizzes.\n")

    print("Fetching trending topics from Google Trends...")
    seo_data = get_seo_topics()
    topics   = seo_data["topics"]
    print(f"Got {len(topics)} SEO briefs.\n")

    published = False
    for i, brief in enumerate(topics, 1):
        title = brief["title"]
        print(f"[{i}/{len(topics)}] {title}")
        print(f"  Focus keyword : {brief['focus_keyword']}")
        print(f"  Target query  : {brief['target_query']}")

        # ── Skip if topic already published ───────────────────────────────────
        if is_topic_used(title):
            print(f"  SKIPPED — topic already exists in Supabase.\n")
            continue

        try:
            print("  Generating blog post...")
            title, content = generate_blog(
                brief,
                blog_links=blog_links,
                quiz_links=quiz_links,
            )

            print("  Searching for image...")
            image_bytes, filename, alt_text = search_image(brief["focus_keyword"])

            print("  Uploading image to WordPress...")
            media_id = upload_image_to_wordpress(image_bytes, filename, alt_text)

            print("  Publishing to WordPress...")
            result   = publish_blog(title, content, brief, featured_media_id=media_id)
            post_url = result.get("link", "")
            print(f"  Published! ID: {result.get('id')} | URL: {post_url}")

            print("  Saving to Supabase...")
            slug = brief.get("url_slug", "")
            push_to_supabase(title, brief, slug)

            published = True
            break  # one blog per run

        except Exception as e:
            print(f"  ERROR: {e} — skipping.")

    if not published:
        print("No new topics found — all topics already exist in Supabase.")

        print()
