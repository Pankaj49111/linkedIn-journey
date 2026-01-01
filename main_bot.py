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

# --- PERSONAL BRANDING ---
MY_NAME = "Pankaj Kumar"

# The CTA (Call to Action) appended to every post
# Note: \n characters ensure visual separation on LinkedIn
FIXED_CTA = f"""
♻️ Found this useful? Repost to save a teammate from debugging hell.

➕ Follow {MY_NAME} for more Backend Engineering war stories.
"""

FIXED_HASHTAGS = "\n\n#backend #engineering #software #java"

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
# TECH FOCUS AREAS
# =============================
TECH_FOCUS_AREAS = {
    "distributed_data": ["Cassandra", "CQRS", "Schema Evolution"],
    "caching": ["Redis", "Cache Invalidation", "Distributed Locking"],
    "async": ["Kafka Consumer Lag", "Idempotency", "Event Ordering"],
    "infra": ["Kubernetes OOMs", "Cold Starts", "Connection Pooling"],
    "observability": ["Misleading Metrics", "Alert Fatigue", "SLIs/SLOs"],
    "ownership": ["API Contracts", "Dependency Drift", "Legacy Migrations"]
}

# =============================
# THEMES
# =============================
THEMES = [
    {"type": "THE ARCHITECTURAL TRAP 🏗️", "tone": "Humble, analytical", "allowed_tech": ["distributed_data", "caching", "async"]},
    {"type": "THE HUMAN ALGORITHM 🤝", "tone": "Reflective, empathetic", "allowed_tech": ["ownership", "async", "observability"]},
    {"type": "THE CRASH 🚨", "tone": "Calm urgency", "allowed_tech": ["infra", "async", "caching"]},
    {"type": "THE FALSE FIX 🔧", "tone": "Analytical, corrective", "allowed_tech": ["caching", "infra"]},
    {"type": "THE METRIC LIE 📊", "tone": "Skeptical, reflective", "allowed_tech": ["observability"]},
    {"type": "THE OWNERSHIP GAP 🧩", "tone": "Leadership-focused", "allowed_tech": ["ownership"]},
    {"type": "THE EUREKA MOMENT 💡", "tone": "Inspiring, energetic", "allowed_tech": ["distributed_data", "caching"]},
    {"type": "THE SILENT VICTORY 🏆", "tone": "Proud, technical", "allowed_tech": ["infra", "observability"]},
    {"type": "THE BORING STACK ❤️", "tone": "Pragmatic, counter-culture", "allowed_tech": ["distributed_data", "infra"]}
]

# =============================
# HELPERS
# =============================
def safe_print(text):
    try:
        print(text.encode("utf-8", "replace").decode("utf-8"))
    except Exception:
        print("Output scrubbed.")

def load_json(path):
    if not os.path.exists(path):
        return {
            "act_index": 0, "episode": 1, "previous_lessons": [],
            "last_themes": [], "last_tech": []
        }
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        return { "act_index": 0, "episode": 1, "previous_lessons": [], "last_themes": [], "last_tech": [] }

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def clean_text(text, forbidden_phrases=None):
    if not text: return ""
    text = text.replace("*", "") # Remove bolding first
    text = re.sub(r'[\(\[].*?[\)\]]', '', text)
    text = re.sub(r'(?i)^(Hook|Lesson|Reflection|Post|Body):', '', text, flags=re.MULTILINE)

    if forbidden_phrases:
        for phrase in forbidden_phrases:
            text = re.sub(re.escape(phrase), '', text, flags=re.IGNORECASE)

    return text.strip()

def select_theme_and_tech(state):
    last_themes = state.get("last_themes", [])
    last_tech = state.get("last_tech", [])

    eligible_themes = [t for t in THEMES if t["type"] not in last_themes[-3:]] or THEMES
    theme = random.choice(eligible_themes)

    tech_pool = []
    for cat in theme["allowed_tech"]:
        tech_pool.extend(TECH_FOCUS_AREAS.get(cat, []))

    final_tech_pool = [t for t in tech_pool if t not in last_tech[-2:]] or tech_pool

    return theme, random.choice(final_tech_pool)

def get_image_from_folder():
    if not os.path.exists(IMAGE_FOLDER): return None
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(IMAGE_FOLDER):
        if file.lower().endswith(valid_extensions):
            return os.path.join(IMAGE_FOLDER, file)
    return None

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

    full_text = text.strip() + "\n\n" + FIXED_CTA.strip() + FIXED_HASHTAGS

    # Defensive Trim (Adjusted for added length)
    if len(full_text) > 2800:
        keep_length = len(FIXED_CTA) + len(FIXED_HASHTAGS) + 5
        available_space = 2797 - keep_length
        text = text[:available_space] + "..."
        full_text = text + "\n\n" + FIXED_CTA.strip() + FIXED_HASHTAGS

    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": full_text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    if image_asset:
        payload["content"] = {"media": {"title": "Tech Insight", "id": image_asset}}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 201: return True
        safe_print(f"❌ LinkedIn Error: {resp.text}")
        return False
    except Exception as e:
        safe_print(f"❌ Network Error: {e}")
        return False

# =============================
# QUALITY GATE
# =============================
QUALITY_GATE_PROMPT = """
Role: Critical Staff+ Editor.

FAIL if ANY are true:
1. No explicit wrong belief admitted by the narrator.
2. No explicit contradiction where system behavior defies expectation.
3. The realization is explained diagnostically instead of discovered emotionally.
4. The failure has no human or operational impact (user-visible damage, on-call pressure, rollback, escalation).
5. Insight feels polished instead of earned through confusion.
6. Moral is missing, longer than one sentence, or sounds like documentation.
7. Tone feels like content creation or explanation.
8. Career stages, Acts, or Themes are referenced explicitly.

PASS_9_PLUS only if:
- Confidence → confusion → realization is felt.
- Stakes are real and immediate.
- Moral implies ownership or responsibility.

Respond with exactly:
PASS_9_PLUS or FAIL
"""

# =============================
# PROMPT BUILDER
# =============================
def build_prompt(act, episode, theme, tech, prev_lessons):
    return f"""
Role:
You are a Senior Backend Engineer reflecting on a real production incident.

INVISIBLE CONTEXT (DO NOT PRINT):
- Life Stage: {act['name']}
- Theme: {theme['type']}
- Tech Focus: {tech}

MANDATORY NARRATIVE SPINE:
1. Identity & humility
2. Confident decision
3. Real-world trigger
4. Failure symptoms
5. CONTRADICTION (things don’t make sense)
6. INFLECTION (realization)
7. LESSON (one sentence)

CONFESSION RULE:
State your wrong assumption naturally (e.g., "I thought...", "I assumed...").
Do NOT write meta-statements like "My explicit wrong belief was...".

RULES:
- No paragraph > 2 lines
- Active voice
- First 2 lines = hook (≤10 words)
- Emojis ≤ 2, inline only
- Stay inside the moment; no retrospectives
- Do NOT give advice (e.g. "Avoid doing X"). Just tell the story.

STRICT FORMAT:
- End the post EXACTLY after the Moral sentence.
- Format:
  "The Moral 👇"
  [One sharp sentence]
  [STOP WRITING HERE]

- Do NOT add hashtags (I will add them).
- Do NOT use markdown.

OUTPUT JSON ONLY:
{{
  "post_text": "...",
  "lesson_extracted": "One uncomfortable lesson in one sentence"
}}

Length: 150–200 words
"""

def generate_with_review(client, prompt, forbidden_phrases):
    for attempt in range(2):
        safe_print(f"🔄 Generation Attempt {attempt + 1}")

        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        content = json.loads(response.text)
        post = clean_text(content["post_text"], forbidden_phrases)

        verdict = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{post}"
        ).text.strip()

        safe_print(f"🕵️ Editor Verdict: {verdict}")

        if verdict == "PASS_9_PLUS":
            content["post_text"] = post
            return content

        prompt += """
        Rewrite with:
        - One explicit wrong belief stated in first person
        - One moment of confusion before the realization
        - One concrete human or operational consequence
        - Insight discovered, not explained
        - Place exactly ONE sentence AFTER the line "The Moral 👇"
        """

    safe_print("❌ Failed strict quality gate twice.")
    sys.exit(1)

# =============================
# DRAFT MODE
# =============================
def run_draft_mode():
    state = load_json(STATE_FILE)
    client = genai.Client(api_key=GEMINI_KEY)

    # 1. Select Content
    act = ACTS[state["act_index"]]
    theme, tech = select_theme_and_tech(state)
    prev = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    # 2. LOG THE CHOICES
    print("\n" + "="*40)
    safe_print(f"🎭 ACT:   {act['name']}")
    safe_print(f"🎰 THEME: {theme['type']}")
    safe_print(f"🛠️ TECH:  {tech}")
    print("="*40 + "\n")

    # 3. Build & Generate
    prompt = build_prompt(act, state["episode"], theme, tech, prev)
    forbidden = [act["name"], theme["type"]]

    content = generate_with_review(client, prompt, forbidden)
    content["meta_theme"] = theme["type"]
    content["meta_tech"] = tech

    save_json(DRAFT_FILE, content)

    print("\n✅ DRAFT SAVED:")
    safe_print(content["post_text"][:150] + "...")

# =============================
# PUBLISH MODE
# =============================
def run_publish_mode():
    draft = load_json(DRAFT_FILE)
    if not draft:
        safe_print("⚠️ No draft found.")
        return

    urn = get_user_urn()
    if not urn:
        safe_print("❌ Invalid LinkedIn token.")
        return

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

    # Post
    success = post_to_linkedin(urn, draft["post_text"], media_urn)
    if not success:
        return

    state = load_json(STATE_FILE)

    # Update History
    state["previous_lessons"].append(draft["lesson_extracted"])
    state.setdefault("last_themes", []).append(draft["meta_theme"])
    state.setdefault("last_tech", []).append(draft["meta_tech"])

    # Trim History
    state["last_themes"] = state["last_themes"][-5:]
    state["last_tech"] = state["last_tech"][-5:]

    # Advance Episode
    state["episode"] += 1
    if state["episode"] > ACTS[state["act_index"]]["max_episodes"]:
        state["episode"] = 1
        state["act_index"] = (state["act_index"] + 1) % len(ACTS)

    save_json(STATE_FILE, state)
    os.remove(DRAFT_FILE)
    if image_path: os.remove(image_path)
    safe_print("🚀 Published successfully.")

# =============================
# ENTRYPOINT
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()

    if args.mode == "draft":
        run_draft_mode()
    elif args.mode == "publish":
        run_publish_mode()