import os
import json
import argparse
import requests
from google import genai # <--- NEW LIBRARY IMPORT
import sys
import time
import urllib.parse
import re
import random

# --- CONFIGURATION ---
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

# Files
STATE_FILE = "story_state.json"
DRAFT_FILE = "current_draft.json"
IMAGE_FOLDER = "images"

# API VERSION CONFIG
LINKEDIN_API_VERSION = "202411"

ACTS = [
    {"name": "ACT I – Foundations & Early Confidence", "max_episodes": 8},
    {"name": "ACT II – Scale Pain & Architectural Stress", "max_episodes": 10},
    {"name": "ACT III – Failures, Incidents, Reality", "max_episodes": 8},
    {"name": "ACT IV – Maturity, Trade-offs, Engineering Wisdom", "max_episodes": 6},
]

# --- THEMES ---
THEMES = [
    {
        "type": "THE CRASH",
        "hook_instruction": "Imply a sudden technical failure, outage, or panic.",
        "tone": "Urgent, chaotic, high-stakes.",
    },
    {
        "type": "THE ARCHITECTURE REGRET",
        "hook_instruction": "Start with a decision that seemed smart 2 years ago but is terrible now.",
        "tone": "Reflective, slightly cynical, 'if I knew then what I know now'.",
    },
    {
        "type": "THE UNPOPULAR OPINION",
        "hook_instruction": "State a controversial opinion about a specific tool (e.g., Microservices, Kubernetes, Hibernate).",
        "tone": "Bold, authoritative, challenging the status quo.",
    },
    {
        "type": "THE DEBUGGING DETECTIVE",
        "hook_instruction": "Describe a bug that was impossible to find (a 'Heisenbug').",
        "tone": "Analytical, mysterious, satisfying reveal.",
    }
]

# --- ROBUST HELPERS ---
def safe_print(text):
    """Prints text while stripping unprintable characters to prevent CI/CD crashes."""
    try:
        print(text.encode('utf-8', 'replace').decode('utf-8'))
    except Exception:
        print("Scrubbed output due to encoding error.")

def load_json(filename):
    if not os.path.exists(filename): return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        safe_print(f"❌ Error loading {filename}: {e}")
        return None

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def get_image_from_folder():
    if not os.path.exists(IMAGE_FOLDER): return None
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(IMAGE_FOLDER):
        if file.lower().endswith(valid_extensions):
            return os.path.join(IMAGE_FOLDER, file)
    return None

def clean_text(text):
    if not text: return ""
    text = re.sub(r'\((Panic|Tension|Reaction|Insight|Theme:.*?)\)', '', text, flags=re.IGNORECASE)
    text = text.encode('utf-8', 'ignore').decode('utf-8')
    return text.strip()

# --- LINKEDIN UTILS ---
def get_user_urn():
    try:
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            safe_print(f"❌ User Info Error: {resp.status_code} - {resp.text}")
            return None
        return resp.json().get("sub")
    except Exception as e:
        safe_print(f"❌ User Info Exception: {e}")
        return None

def upload_image_to_linkedin(urn, image_path):
    safe_print("Uploading image...")
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    headers = {
        'Authorization': f'Bearer {LINKEDIN_TOKEN}',
        'Content-Type': 'application/json',
        'LinkedIn-Version': LINKEDIN_API_VERSION,
        'X-Restli-Protocol-Version': '2.0.0'
    }
    payload = {"initializeUploadRequest": {"owner": f"urn:li:person:{urn}"}}

    try:
        resp = requests.post(init_url, headers=headers, json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            safe_print(f"❌ Init Upload Error: {resp.status_code} - {resp.text}")
            return None

        data = resp.json().get('value') or resp.json()
        upload_url = data.get('uploadUrl')
        image_urn = data.get('image') or data.get('imageUrn')

        if not upload_url or not image_urn:
            return None

        with open(image_path, 'rb') as f:
            put_resp = requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f, timeout=60)
            if put_resp.status_code not in (200, 201):
                safe_print(f"❌ Binary Upload Error: {put_resp.status_code} - {put_resp.text}")
                return None

        return image_urn
    except Exception as e:
        safe_print(f"❌ Upload Exception: {e}")
        return None

def poll_image_status(image_urn, timeout_seconds=60, poll_interval=2):
    if not image_urn: return False

    encoded_urn = urllib.parse.quote(image_urn)
    url = f"https://api.linkedin.com/rest/images/{encoded_urn}"

    safe_print(f"⏳ Polling image status...")
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0"
    }

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                status = None
                if "value" in data: status = data["value"].get("status") or data["value"].get("processingState")
                else: status = data.get("status") or data.get("processingState")

                if status == "AVAILABLE":
                    safe_print("✅ Image is AVAILABLE.")
                    return True
                elif status in ["FAILED", "ERROR"]:
                    safe_print(f"❌ Image processing failed: {status}")
                    return False
            time.sleep(poll_interval)
        except Exception as e:
            safe_print(f"Polling warning: {e}")
            time.sleep(poll_interval)

    safe_print("❌ Polling timed out.")
    return False

def post_to_linkedin(urn, text, image_asset=None, max_retries=2):
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION
    }

    text = clean_text(text)
    MAX_LEN = 2800
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 3] + "..."

    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    if image_asset:
        payload["content"] = {
            "media": {
                "title": "Tech Insight",
                "id": image_asset
            }
        }

    attempt = 0
    while attempt <= max_retries:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 201:
                return True

            if 400 <= resp.status_code < 500:
                safe_print(f"❌ Post Rejected ({resp.status_code}): {resp.text}")
                return False

            safe_print(f"⚠️ Server Error ({resp.status_code}), retrying...")
        except Exception as e:
            safe_print(f"⚠️ Network Exception: {e}")

        attempt += 1
        time.sleep(2 ** attempt)
    return False

# --- CORE LOGIC ---
def run_draft_mode():
    safe_print("🌅 STARTING DRAFT MODE...")
    state = load_json(STATE_FILE)
    if not state: state = {"act_index": 0, "episode": 1, "previous_lessons": []}

    # --- NEW CLIENT INITIALIZATION ---
    client = genai.Client(api_key=GEMINI_KEY)

    act = ACTS[state["act_index"]]
    previous_lessons = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    current_theme = random.choice(THEMES)
    safe_print(f"🎰 Selected Theme: {current_theme['type']}")

    prompt = f"""
    Role: You are a Senior Backend Engineer writing high-performing LinkedIn posts.
    
    Current Life Stage: {act['name']} (Episode {state['episode']})
    Previous Lessons:
    {previous_lessons}
    
    TECH STACK (STRICT):
    Java 17/21, Spring Boot, Hibernate, Postgres, Cassandra, Redis, Kafka, Docker, Kubernetes.
    
    # --- TODAY'S THEME: {current_theme['type']} ---
    # TONE: {current_theme['tone']}
    # HOOK REQUIREMENT: {current_theme['hook_instruction']}
    
    WRITING RULES (MANDATORY):
    1. **NO MARKDOWN:** Do NOT use bold or italics. Use CAPS for emphasis.
    2. **NO STAGE DIRECTIONS:** Do NOT write text like (Theme: X).
    3. **HOOK RULE:** First 2 lines only. Max 10 words per line. Use the 'HOOK REQUIREMENT'.
    4. **STORY RULES:** Short, punchy paragraphs. Exactly ONE inflection point.
    5. **REFLECTION RULE:** Explicitly admit a mistake/opinion. Confession, not tutorial.
    6. **EMOJI RULES:** Inline only. No emojis at the end.
    7. **MORAL RULE:** Standalone line: The Moral 👇. Follow with ONE sharp sentence.
    8. **INTERACTION RULE:** End with ONE sharp question.
    
    FORMAT RULE:
    End with hashtags: #backend #engineering #software #java
    
    OUTPUT FORMAT (JSON ONLY):
    {{
      "post_text": "...",
      "lesson_extracted": "One uncomfortable lesson in one sentence"
    }}
    
    Length: 150–200 words.
    """

    try:
        # --- NEW GENERATION METHOD ---
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json"
            }
        )

        # In the new SDK, response.text is directly accessible
        content = json.loads(response.text)
        content["post_text"] = clean_text(content["post_text"])

        save_json(DRAFT_FILE, content)
        safe_print(f"✅ Draft saved to {DRAFT_FILE}.")
        safe_print("🔍 PREVIEW:")
        safe_print(content["post_text"][:100] + "...")

    except Exception as e:
        safe_print(f"❌ Generation Failed: {e}")
        exit(1)

def run_publish_mode():
    safe_print("🚀 STARTING PUBLISH MODE...")
    draft = load_json(DRAFT_FILE)
    if not draft:
        safe_print("⚠️ No draft found! Skipping.")
        exit(0)

    safe_print("\n📝 CONTENT TO POST:")
    safe_print("-" * 20)
    safe_print(draft["post_text"])
    safe_print("-" * 20 + "\n")

    image_path = get_image_from_folder()
    if image_path: safe_print(f"📸 Found image: {image_path}")
    else: safe_print("📝 No image found. Text only.")

    urn = get_user_urn()
    if not urn:
        safe_print("❌ CRITICAL: Invalid Token.")
        exit(1)

    media_urn = None
    if image_path:
        media_urn = upload_image_to_linkedin(urn, image_path)
        if media_urn:
            is_ready = poll_image_status(media_urn)
            if not is_ready:
                safe_print("⚠️ Image not ready. Posting TEXT ONLY.")
                media_urn = None
        else:
            safe_print("⚠️ Upload failed. Posting TEXT ONLY.")

    success = post_to_linkedin(urn, draft["post_text"], media_urn)

    if success:
        safe_print("✅ Published successfully!")

        state = load_json(STATE_FILE)
        if not state: state = {"act_index": 0, "episode": 1, "previous_lessons": []}

        state["previous_lessons"].append(draft["lesson_extracted"])
        state["episode"] += 1

        current_act = ACTS[state["act_index"]]
        if state["episode"] > current_act["max_episodes"]:
            state["act_index"] += 1
            state["episode"] = 1
            if state["act_index"] >= len(ACTS): state["act_index"] = 0

        save_json(STATE_FILE, state)

        os.remove(DRAFT_FILE)
        if image_path: os.remove(image_path)
        safe_print("🧹 Cleanup complete.")
    else:
        safe_print("❌ Final Post Failed.")
        exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()

    if args.mode == "draft": run_draft_mode()
    elif args.mode == "publish": run_publish_mode()