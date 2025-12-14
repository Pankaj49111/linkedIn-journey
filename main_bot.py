import os
import json
import argparse
import requests
import google.generativeai as genai
import sys
import time
import urllib.parse # <--- Added for fixing the 400 Error

# Force UTF-8 for logs
sys.stdout.reconfigure(encoding='utf-8')

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
    {"name": "ACT I – Foundations & Early Confidence", "max_episodes": 6},
    {"name": "ACT II – Scale Pain & Architectural Stress", "max_episodes": 8},
    {"name": "ACT III – Failures, Incidents, Reality", "max_episodes": 7},
    {"name": "ACT IV – Maturity, Trade-offs, Engineering Wisdom", "max_episodes": 5},
]

# --- HELPERS ---
def load_json(filename):
    if not os.path.exists(filename): return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading {filename}: {e}")
        return None

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_image_from_folder():
    if not os.path.exists(IMAGE_FOLDER): return None
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(IMAGE_FOLDER):
        if file.lower().endswith(valid_extensions):
            return os.path.join(IMAGE_FOLDER, file)
    return None

# --- LINKEDIN UTILS ---
def get_user_urn():
    try:
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"❌ User Info Error: {resp.status_code} - {resp.text}")
            return None
        return resp.json().get("sub")
    except Exception as e:
        print(f"❌ User Info Exception: {e}")
        return None

def upload_image_to_linkedin(urn, image_path):
    print("Uploading image...")
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    headers = {
        'Authorization': f'Bearer {LINKEDIN_TOKEN}',
        'Content-Type': 'application/json',
        'LinkedIn-Version': LINKEDIN_API_VERSION,
        'X-Restli-Protocol-Version': '2.0.0'
    }
    payload = {"initializeUploadRequest": {"owner": f"urn:li:person:{urn}"}}

    try:
        # 1. Initialize
        resp = requests.post(init_url, headers=headers, json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            print(f"❌ Init Upload Error: {resp.status_code} - {resp.text}")
            return None

        data = resp.json().get('value') or resp.json()
        upload_url = data.get('uploadUrl')
        image_urn = data.get('image') or data.get('imageUrn')

        if not upload_url or not image_urn:
            return None

        # 2. Upload Bytes
        with open(image_path, 'rb') as f:
            put_resp = requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f, timeout=60)
            if put_resp.status_code not in (200, 201):
                print(f"❌ Binary Upload Error: {put_resp.status_code} - {put_resp.text}")
                return None

        # We return the full URN. We do NOT split it.
        # The API needs the full URN for polling.
        return image_urn

    except Exception as e:
        print(f"❌ Upload Exception: {e}")
        return None

def poll_image_status(image_urn, timeout_seconds=60, poll_interval=2):
    """Checks if image is processed and ready to post."""
    if not image_urn: return False

    # FIX for 400 Error: URL Encode the URN (urn:li:image:123 -> urn%3Ali%3Aimage%3A123)
    encoded_urn = urllib.parse.quote(image_urn)
    url = f"https://api.linkedin.com/rest/images/{encoded_urn}"

    print(f"⏳ Polling image status for URN: {image_urn}...")

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
                    print("✅ Image is AVAILABLE.")
                    return True
                elif status in ["FAILED", "ERROR"]:
                    print(f"❌ Image processing failed: {status}")
                    return False
            else:
                # Often returns 404 while processing initially
                pass
            time.sleep(poll_interval)
        except Exception as e:
            print(f"Polling warning: {e}")
            time.sleep(poll_interval)

    print("❌ Polling timed out.")
    return False

def post_to_linkedin(urn, text, image_asset=None, max_retries=2):
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION
    }

    # Defensive trim
    MAX_LEN = 2800
    text = text.strip()
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 3] + "..."

    # --- PAYLOAD CONSTRUCTION (FIXED 500 ERROR) ---
    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": text,  # <--- FIXED: Must be a direct string
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
                "id": image_asset # Single object, not a list
            }
        }

    # Retry Logic
    attempt = 0
    while attempt <= max_retries:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 201:
                return True

            if 400 <= resp.status_code < 500:
                print(f"❌ Post Rejected ({resp.status_code}): {resp.text}")
                return False

            print(f"⚠️ Server Error ({resp.status_code}), retrying...")

        except Exception as e:
            print(f"⚠️ Network Exception: {e}")

        attempt += 1
        time.sleep(2 ** attempt)

    return False

# --- CORE LOGIC ---
def run_draft_mode():
    print("🌅 STARTING DRAFT MODE...")
    state = load_json(STATE_FILE)
    if not state: state = {"act_index": 0, "episode": 1, "previous_lessons": []}

    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-flash-latest")

    act = ACTS[state["act_index"]]
    previous_lessons = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    prompt = f"""
    Role: You are a Senior Backend Engineer sharing a raw, authentic story on LinkedIn.
    
    Current Life Stage: {act['name']} (Episode {state['episode']})
    Context: {previous_lessons}
    
    STRICT TECH STACK: Java 17/21, Spring Boot, Hibernate, Postgres, Cassandra, Redis, Kafka, Docker, K8s.
    
    STRICT FORMATTING:
    1. Hook -> Story -> (2 Blank Lines) -> Moral -> (2 Blank Lines) -> Hashtags.
    2. Tone: Casual, cynical, smart.
    3. Hashtags: #backend #engineering #software #java
    
    OUTPUT JSON: {{ "post_text": "...", "lesson_extracted": "..." }}
    """

    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        content = json.loads(response.text)
        save_json(DRAFT_FILE, content)
        print(f"✅ Draft saved to {DRAFT_FILE}.")
        print("🔍 PREVIEW:")
        print(content["post_text"][:100] + "...")
    except Exception as e:
        print(f"❌ Generation Failed: {e}")
        exit(1)

def run_publish_mode():
    print("🚀 STARTING PUBLISH MODE...")
    draft = load_json(DRAFT_FILE)
    if not draft:
        print("⚠️ No draft found! Skipping.")
        exit(0)

    print("\n📝 CONTENT TO POST:")
    print("-" * 20)
    print(draft["post_text"])
    print("-" * 20 + "\n")

    image_path = get_image_from_folder()
    if image_path: print(f"📸 Found image: {image_path}")
    else: print("📝 No image found. Text only.")

    urn = get_user_urn()
    if not urn:
        print("❌ CRITICAL: Invalid Token.")
        exit(1)

    media_urn = None

    # Image Upload & Polling
    if image_path:
        media_urn = upload_image_to_linkedin(urn, image_path)
        if media_urn:
            is_ready = poll_image_status(media_urn) # Pass the full URN
            if not is_ready:
                print("⚠️ Image not ready. Posting TEXT ONLY.")
                media_urn = None
        else:
            print("⚠️ Upload failed. Posting TEXT ONLY.")

    # Post
    success = post_to_linkedin(urn, draft["post_text"], media_urn)

    if success:
        print("✅ Published successfully!")

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
        print("🧹 Cleanup complete.")
    else:
        print("❌ Final Post Failed.")
        exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()

    if args.mode == "draft": run_draft_mode()
    elif args.mode == "publish": run_publish_mode()