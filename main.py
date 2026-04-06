import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from openai import AzureOpenAI
import os

load_dotenv()

# Azure OpenAI config
azure_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY", "5JrKsbth7THL1EJ5p4HLhnWo0bjuw3FaRoLv1zLWGF9e6Ip71reLJQQJ99ALACHYHv6XJ3w3AAAAACOGquzS"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "https://ai-degensid9734ai299032318840.cognitiveservices.azure.com/"),
)

DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-chat")

# WordPress config
WP_URL = "https://blogs.melloai.health/wp-json/wp/v2/posts"
WP_MEDIA_URL = "https://blogs.melloai.health/wp-json/wp/v2/media"
WP_USERNAME = "melloai"
WP_PASSWORD = os.getenv("app_password")

# Pexels config
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")


def generate_blog(topic: str) -> tuple[str, str]:
    """Generate a blog title and content using Azure GPT-5."""
    response = azure_client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional health and wellness blog writer. "
                    "Write engaging, informative blog posts in HTML format suitable for WordPress.\n\n"
                    "Follow these rules strictly:\n"
                    "1. STRUCTURE: Begin with an introductory first paragraph that does NOT contain the main keyword. "
                    "The first paragraph should hook the reader with a relatable scenario, question, or surprising fact — no keyword stuffing.\n"
                    "2. KEYWORD DENSITY: Keep the overall keyword density at or below 2%. "
                    "Use the main keyword naturally; do not force it into every paragraph.\n"
                    "3. WORD COUNT: The total blog body (excluding title) must be between 700 and 1000 words.\n"
                    "4. CTA: End the post with a clear Call-To-Action (CTA) inside a <div class=\"cta-block\"> tag. "
                    "The CTA should encourage the reader to take a specific next step (e.g. book a consultation, subscribe, try a technique today).\n"
                    "5. FORMAT: Use proper HTML tags — <h2> for subheadings, <p> for paragraphs, <ul>/<li> for lists where appropriate.\n\n"
                    "Return your response as:\nTITLE: <title>\n\n<html content>"
                ),
            },
            {
                "role": "user",
                "content": f"Write a blog post about: {topic}",
            },
        ],
        temperature=0.7,
        max_tokens=2500,
    )

    raw = response.choices[0].message.content.strip()

    if raw.startswith("TITLE:"):
        lines = raw.split("\n", 2)
        title = lines[0].replace("TITLE:", "").strip()
        content = lines[2].strip() if len(lines) > 2 else lines[1].strip()
    else:
        title = "AI Generated Health Blog"
        content = raw

    return title, content


def search_image(query: str) -> tuple[bytes, str, str]:
    """Search Pexels for a relevant image. Returns (image_bytes, filename, alt_text)."""
    if not PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY is not set in .env")

    search_url = "https://api.pexels.com/v1/search"
    params = {
        "query": query,
        "per_page": 1,
        "orientation": "landscape",
    }
    headers = {"Authorization": PEXELS_API_KEY}

    resp = requests.get(search_url, params=params, headers=headers)
    resp.raise_for_status()
    results = resp.json().get("photos", [])

    if not results:
        raise ValueError(f"No images found on Pexels for query: {query}")

    photo = results[0]
    image_url = photo["src"]["large2x"]
    alt_text = photo.get("alt") or query
    photographer = photo["photographer"]
    filename = f"{query.replace(' ', '_')[:50]}.jpg"

    print(f"  Image by {photographer} on Pexels: {image_url}")

    image_bytes = requests.get(image_url).content
    return image_bytes, filename, alt_text


def upload_image_to_wordpress(image_bytes: bytes, filename: str, alt_text: str) -> int:
    """Upload image to WordPress media library. Returns the media ID."""
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/jpeg",
    }

    resp = requests.post(
        WP_MEDIA_URL,
        auth=HTTPBasicAuth(WP_USERNAME, WP_PASSWORD),
        headers=headers,
        data=image_bytes,
    )
    resp.raise_for_status()
    media = resp.json()
    media_id = media["id"]

    # Set alt text
    requests.post(
        f"{WP_MEDIA_URL}/{media_id}",
        auth=HTTPBasicAuth(WP_USERNAME, WP_PASSWORD),
        json={"alt_text": alt_text},
    )

    print(f"  Uploaded image to WordPress, media ID: {media_id}")
    return media_id


def publish_blog(title: str, content: str, featured_media_id: int = None) -> dict:
    """Publish the blog post to WordPress with an optional featured image."""
    data = {
        "title": title,
        "content": content,
        "status": "publish",
    }
    if featured_media_id:
        data["featured_media"] = featured_media_id

    response = requests.post(
        WP_URL,
        auth=HTTPBasicAuth(WP_USERNAME, WP_PASSWORD),
        json=data,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    topic = "The benefits of mindfulness meditation for mental health"

    print(f"Generating blog post about: {topic}")
    title, content = generate_blog(topic)
    print(f"Title: {title}")

    print("Searching for a relevant image...")
    image_bytes, filename, alt_text = search_image(topic)

    print("Uploading image to WordPress...")
    media_id = upload_image_to_wordpress(image_bytes, filename, alt_text)

    print("Publishing to WordPress...")
    result = publish_blog(title, content, featured_media_id=media_id)
    print(f"Published! Post ID: {result.get('id')}, URL: {result.get('link')}")
