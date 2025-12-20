import os
import json
import argparse
import requests
from google import genai
import sys
import time
import urllib.parse
import re
import random

# =============================
# FORCE UTF-8 OUTPUT
# =============================
sys.stdout.reconfigure(encoding="utf-8")

# =============================
# CONFIGURATION
# =============================
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

STATE_FILE = "story_state.json"
DRAFT_FILE = "current_draft.json"
IMAGE_FOLDER = "images"

LINKEDIN_API_VERSION = "202411"

# =============================
# ACTS (CAREER ARC)
# =============================
ACTS = [
    {"name": "ACT I – Early Confidence & First Systems", "max_episodes": 8},
    {"name": "ACT II – Scaling Pressure & Hidden Complexity", "max_episodes": 10},
    {"name": "ACT III – Incidents, Failures, Reality", "max_episodes": 8},
    {"name": "ACT IV – Trade-offs & Simplification", "max_episodes": 6},
    {"name": "ACT V – Ownership, Leadership, People Systems", "max_episodes": 6},
    {"name": "ACT VI – Judgment, Restraint, Engineering Wisdom", "max_episodes": 6},
]

# =============================
# TECH FOCUS AREAS (CATEGORIZED)
# =============================
TECH_FOCUS_AREAS = {
    "distributed_data": [
        "Cassandra (Consistency vs Availability)",
        "CQRS & Dual Writes",
        "Schema Evolution & Backfills"
    ],
    "caching": [
        "Redis & Distributed Locking",
        "Cache Invalidation & TTLs"
    ],
    "async": [
        "Kafka Consumer Lag & Retries",
        "At-Least-Once Delivery & Idempotency"
    ],
    "infra": [
        "Autoscaling & Cold Starts",
        "Thread Pools & Resource Exhaustion"
    ],
    "observability": [
        "Misleading Metrics & Green Dashboards",
        "Alert Fatigue & SLIs"
    ],
    "ownership": [
        "Shared Services & API Contracts",
        "Platform vs Product Boundaries"
    ]
}

# =============================
# THEMES WITH COMPATIBILITY
# =============================
THEMES = [
    {
        "type": "THE ARCHITECTURAL TRAP 🏗️",
        "tone": "Humble, analytical",
        "allowed_tech": ["distributed_data", "caching", "async"]
    },
    {
        "type": "THE HUMAN ALGORITHM 🤝",
        "tone": "Reflective, empathetic",
        "allowed_tech": ["ownership", "async", "observability"]
    },
    {
        "type": "THE CRASH 🚨",
        "tone": "Calm urgency",
        "allowed_tech": ["infra", "async", "caching"]
    },
    {
        "type": "THE FALSE FIX 🔧",
        "tone": "Analytical, corrective",
        "allowed_tech": ["caching", "infra"]
    },
    {
        "type": "THE METRIC LIE 📊",
        "tone": "Skeptical, reflective",
        "allowed_tech": ["observability"]
    },
    {
        "type": "THE OWNERSHIP GAP 🧩",
        "tone": "Leadership-focused",
        "allowed_tech": ["ownership"]
    }
]

# =============================
# HELPERS
# =============================
def safe_print(text):
    try:
        print(text.encode('utf-8', 'replace').decode('utf-8'))
    except Exception:
        print("Scrubbed output due to encoding error.")

def load_json(path):
    if not os.path.exists(path): return None
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def clean_text(text):
    if not text: return ""
    text = re.sub(r'[\(\[].*?[\)\]]', '', text)
    text = re.sub(r'(?i)^(Hook|Lesson|Moral|Reflection):', '', text, flags=re.MULTILINE)
    text = text.replace('*', '')
    return text.strip()

def get_image_from_folder():
    if not os.path.exists(IMAGE_FOLDER): return None
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(IMAGE_FOLDER):
        if file.lower().endswith(valid_extensions):
            return os.path.join(IMAGE_FOLDER, file)
    return None

# =============================
# SELECTION LOGIC
# =============================
def select_theme_and_tech(state):
    last_themes = state.get("last_themes", [])
    last_tech = state.get("last_tech", [])

    eligible_themes = [t for t in THEMES if t["type"] not in last_themes[-3:]]
    if not eligible_themes: eligible_themes = THEMES

    theme = random.choice(eligible_themes)

    allowed_categories = theme["allowed_tech"]
    tech_pool = []
    for cat in allowed_categories:
        tech_pool.extend(TECH_FOCUS_AREAS.get(cat, []))

    final_tech_pool = [t for t in tech_pool if t not in last_tech[-2:]]
    if not final_tech_pool: final_tech_pool = tech_pool

    tech = random.choice(final_tech_pool)
    return theme, tech

# =============================
# QUALITY GATE (STRICT)
# =============================
QUALITY_GATE_PROMPT = """
Role:
You are a critical LinkedIn editor evaluating whether this post is
publication-ready for a Staff+ backend engineer.

Your job is NOT to improve the post.
Your job is to decide if it is excellent.

FAIL the post if ANY of the following are true:

1. The hook is informative but not experiential.
2. The lesson is correct but feels obvious or polished.
3. The failure feels explainable without emotional confusion.
4. The narrator does not appear visibly lost or uncertain at any point.
5. The realization feels fully formed instead of emerging from contradiction or confusion.
6. The post sounds like reflection without struggle.
7. Mid-level engineers can read it, but senior engineers would not pause on it.

PASS_9_PLUS only if:
- The reader feels confidence → confusion → realization.
- The insight feels earned, not presented.
- The post would not embarrass a Staff+ engineer to repost.

OUTPUT RULE (STRICT):
Respond with exactly ONE token:
PASS_9_PLUS or FAIL
"""

# =============================
# PROMPT BUILDER
# =============================
def build_prompt(act, episode, theme, tech, prev_lessons):
    return f"""
Role:
You are a Senior Backend Engineer reflecting on real production experience.
You write like someone who has been wrong in production before.

Current Life Stage:
{act['name']} (Episode {episode})

Previous Lessons:
{prev_lessons}

Context:
- Theme: {theme['type']}
- Tone: {theme['tone']}
- Tech Focus: {tech}

AUDIENCE & SIGNALING (INCLUSIVITY RULE):
Write so that:
- Mid-level engineers can understand the failure.
- Senior engineers recognize the mistake.
- Staff-level engineers respect the framing.
Do not explicitly teach or explain.

MANDATORY NARRATIVE SPINE:
1. Identity & humility (Grounded, no drama)
2. Confident decision (Reasonable at the time)
3. Real-world trigger (Traffic/Scale/Pressure)
4. Failure symptoms (Pain before root cause)
5. Inflection point (Standalone line)
6. Lesson earned (One reflective sentence)

RULES:
- No paragraph > 2 lines (Visual Flow)
- Active voice ("I saw" not "It was seen")
- First 2 lines = hook (≤10 words)
- Emojis ≤ 2, inline only
- Context Rule: explain design goal first

MORAL:
Use ONE:
- The Moral 👇
- What this taught me 👇

FORMAT:
End with:
#backend #engineering #software #java

OUTPUT JSON ONLY:
{{
  "post_text": "...",
  "lesson_extracted": "One uncomfortable lesson in one sentence"
}}

Length: 150–200 words
"""

# =============================
# GENERATE + REVIEW LOOP
# =============================
def generate_with_review(client, prompt):
    for attempt in range(2):
        safe_print(f"🔄 Generation Attempt {attempt + 1}...")

        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        content = json.loads(response.text)
        post = clean_text(content["post_text"])

        # Editor Check
        review_resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{post}"
        ).text.strip()

        safe_print(f"🕵️ Editor Verdict: {review_resp}")

        # STRICT CHECK FOR "PASS_9_PLUS"
        if review_resp.strip() == "PASS_9_PLUS":
            content["post_text"] = post
            return content

        # REWRITE INSTRUCTION (TARGETED)
        prompt += """
        Rewrite with:
        - A sharper, more experiential hook (felt, not explained)
        - One explicit moment of confusion or contradiction before the realization
        - A clearer emotional gap between confidence and failure
        - Less polish in the insight, more discovery
        """

    # Fallback to the last attempt if it fails twice,
    # but print a warning (in real prod you might want to exit(1))
    safe_print("⚠️ Warning: Published draft failed strict quality gate twice.")
    return content

# =============================
# LINKEDIN UTILS
# =============================
def get_user_urn():
    try:
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200: return None
        return resp.json().get("sub")
    except Exception: return None

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
        data = resp.json().get('value') or resp.json()
        upload_url = data.get('uploadUrl')
        image_urn = data.get('image') or data.get('imageUrn')

        with open(image_path, 'rb') as f:
            requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f, timeout=60)

        return image_urn
    except Exception as e:
        safe_print(f"❌ Upload Exception: {e}")
        return None

def poll_image_status(image_urn):
    if not image_urn: return False
    encoded_urn = urllib.parse.quote(image_urn)
    url = f"https://api.linkedin.com/rest/images/{encoded_urn}"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0"
    }

    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            status = None
            if "value" in data: status = data["value"].get("status") or data["value"].get("processingState")
            else: status = data.get("status") or data.get("processingState")

            if status == "AVAILABLE": return True
            if status in ["FAILED", "ERROR"]: return False
            time.sleep(2)
        except Exception: time.sleep(2)
    return False

def post_to_linkedin(urn, text, image_asset=None):
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION
    }

    # Trim to safety limit
    if len(text) > 2800: text = text[:2797] + "..."

    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    if image_asset:
        payload["content"] = {"media": {"title": "Tech Insight", "id": image_asset}}

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code == 201: return True

    safe_print(f"❌ Post Failed: {resp.text}")
    return False

# =============================
# MAIN LOGIC
# =============================
def run_draft_mode():
    safe_print("🌅 STARTING DRAFT MODE...")
    state = load_json(STATE_FILE)
    if not state:
        state = {
            "act_index": 0, "episode": 1, "previous_lessons": [],
            "last_themes": [], "last_tech": []
        }

    client = genai.Client(api_key=GEMINI_KEY)

    act = ACTS[state["act_index"]]
    theme, tech = select_theme_and_tech(state)
    prev_lessons = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    safe_print(f"🎭 Act: {act['name']}")
    safe_print(f"🎰 Theme: {theme['type']}")
    safe_print(f"🛠️ Tech: {tech}")

    prompt = build_prompt(act, state["episode"], theme, tech, prev_lessons)
    content = generate_with_review(client, prompt)

    # Save Meta for Rotation Logic (consumed on publish)
    content["meta_theme"] = theme["type"]
    content["meta_tech"] = tech

    save_json(DRAFT_FILE, content)

    print("\n" + "="*50)
    safe_print("✅ DRAFT GENERATED & SAVED")
    print("="*50)
    safe_print(content["post_text"])

def run_publish_mode():
    safe_print("🚀 STARTING PUBLISH MODE...")
    draft = load_json(DRAFT_FILE)
    if not draft:
        safe_print("⚠️ No draft found! Run --mode draft first.")
        return

    urn = get_user_urn()
    if not urn:
        safe_print("❌ CRITICAL: Invalid Token.")
        exit(1)

    # Image Handling
    media_urn = None
    image_path = get_image_from_folder()
    if image_path:
        safe_print(f"📸 Found image: {image_path}")
        media_urn = upload_image_to_linkedin(urn, image_path)
        if media_urn and poll_image_status(media_urn):
            safe_print("✅ Image Ready.")
        else:
            safe_print("⚠️ Image failed. Posting text only.")
            media_urn = None

    success = post_to_linkedin(urn, draft["post_text"], media_urn)

    if success:
        safe_print("✅ Published successfully!")

        # --- UPDATE STATE (Commit Rotation & Episode) ---
        state = load_json(STATE_FILE)
        if not state: state = {"act_index": 0, "episode": 1, "previous_lessons": [], "last_themes": [], "last_tech": []}

        state["previous_lessons"].append(draft["lesson_extracted"])
        state["episode"] += 1

        # Update Rotation History
        if "meta_theme" in draft: state.setdefault("last_themes", []).append(draft["meta_theme"])
        if "meta_tech" in draft: state.setdefault("last_tech", []).append(draft["meta_tech"])

        # Trim History
        state["last_themes"] = state["last_themes"][-5:]
        state["last_tech"] = state["last_tech"][-5:]

        # Handle Act Progression
        current_act = ACTS[state["act_index"]]
        if state["episode"] > current_act["max_episodes"]:
            state["act_index"] = (state["act_index"] + 1) % len(ACTS)
            state["episode"] = 1

        save_json(STATE_FILE, state)

        # Cleanup
        os.remove(DRAFT_FILE)
        if image_path: os.remove(image_path)
    else:
        safe_print("❌ Final Post Failed.")
        exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()

    if args.mode == "draft": run_draft_mode()
    elif args.mode == "publish": run_publish_mode()