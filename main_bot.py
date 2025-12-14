import os
import json
import argparse
import requests
import google.generativeai as genai
import sys
import time

# Force UTF-8 for logs to prevent crashes with emojis/unicode
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
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return None


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_image_from_folder():
    if not os.path.exists(IMAGE_FOLDER):
        return None
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
            print(f"User Info Error: {resp.status_code} - {resp.text}")
            return None
        return resp.json().get("sub")
    except Exception as e:
        print(f"User Info Exception: {e}")
        return None


def upload_image_to_linkedin(urn, image_path):
    """
    Initializes the image upload, PUTs the binary and returns:
    (image_urn, image_id) on success, or (None, None) on failure.
    image_urn example: urn:li:image:ABC123
    image_id example: ABC123
    """
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
        resp = requests.post(init_url, headers=headers, json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            print(f"Init Upload Error: {resp.status_code} - {resp.text}")
            return None, None

        data = resp.json().get('value') or resp.json()
        upload_url = data.get('uploadUrl')
        image_urn = data.get('image') or data.get('imageUrn')  # defensive keys

        if not upload_url or not image_urn:
            print(f"Init Upload missing fields: {data}")
            return None, None

        # PUT binary
        with open(image_path, 'rb') as f:
            put_resp = requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f,
                                    timeout=60)
            if put_resp.status_code not in (200, 201):
                print(f"Binary Upload Error: {put_resp.status_code} - {put_resp.text}")
                return None, None

        # Extract id portion from urn if possible
        image_id = None
        try:
            # urn:li:image:ABC123  -> ABC123
            image_id = image_urn.split(":")[-1]
        except Exception:
            image_id = None

        return image_urn, image_id
    except Exception as e:
        print(f"Upload Exception: {e}")
        return None, None


def poll_image_status(image_id, timeout_seconds=60, poll_interval=2):
    """
    Polls the LinkedIn images API until the image asset is available or timeout.
    Returns True if AVAILABLE, False otherwise.
    """
    if not image_id:
        print("No image_id provided to poll.")
        return False

    url = f"https://api.linkedin.com/rest/images/{image_id}"
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
                body = resp.json()
                # Defensive checks for various possible fields
                status = None
                # common shapes: { "value": { "status": "AVAILABLE" } } or { "processingState": "AVAILABLE" } or { "status": "AVAILABLE" }
                if isinstance(body, dict):
                    # check nested 'value'
                    if "value" in body and isinstance(body["value"], dict):
                        status = body["value"].get("status") or body["value"].get("processingState")
                    # top-level
                    status = status or body.get("status") or body.get("processingState")
                if status:
                    status_upper = str(status).upper()
                    print(f"Image status: {status_upper}")
                    if status_upper in ("AVAILABLE", "SUCCEEDED"):
                        return True
                    if status_upper in ("FAILED", "ERROR"):
                        return False
            else:
                # 404 or other codes are possible while processing
                print(f"Polling: received {resp.status_code}. Waiting...")
        except Exception as e:
            print(f"Polling exception: {e}")

        time.sleep(poll_interval)

    print("Polling timed out waiting for image to become AVAILABLE.")
    return False


def post_to_linkedin(urn, text, image_asset=None, max_retries=2):
    """
    Posts to LinkedIn. If image_asset is provided, attaches it.
    Retries on 5xx errors.
    Returns True on success, False on permanent failure.
    """
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION
    }

    # Defensive trim (LinkedIn soft limit)
    MAX_LEN = 2800
    text = text.strip()
    if len(text) > MAX_LEN:
        print(f"Text length {len(text)} exceeds limit. Trimming.")
        text = text[:MAX_LEN - 3] + "..."

    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": {"text": text},
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
        # Use media as a list for compatibility; single image still uses a one-item list.
        payload["content"] = {
            "media": [
                {
                    "id": image_asset,
                    "title": "Tech Insight"
                }
            ]
        }

    attempt = 0
    while attempt <= max_retries:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 201:
                return True
            # On 4xx, return failure immediately (bad request/auth)
            if 400 <= resp.status_code < 500:
                print(f"Post Creation Error: {resp.status_code} - {resp.text}")
                return False
            # On server error, retry
            print(f"Post attempt {attempt + 1} returned {resp.status_code}. Body: {resp.text}")
        except Exception as e:
            print(f"Exception posting to LinkedIn: {e}")

        attempt += 1
        time.sleep(2 ** attempt)  # exponential backoff

    print("Exceeded max retries posting to LinkedIn.")
    return False


# --- CORE LOGIC ---
def run_draft_mode():
    print("STARTING DRAFT MODE...")
    state = load_json(STATE_FILE)
    if not state:
        state = {"act_index": 0, "episode": 1, "previous_lessons": []}

    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-flash-latest")

    act = ACTS[state["act_index"]]
    previous_lessons = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    prompt = f"""
Role: You are a Senior Backend Engineer sharing a raw, authentic story on LinkedIn.

Current Life Stage: {act['name']} (Episode {state['episode']})
Context (What you already learned): {previous_lessons}

STRICT TECH STACK (WHITELIST):
- Languages: Java 17 or Java 21 ONLY.
- Frameworks: Spring Boot, Hibernate.
- Data: PostgreSQL (SQL), Cassandra (NoSQL), Redis (Cache).
- Async/Ops: Kafka, Docker, Kubernetes (K8s).
- DO NOT mention: Python, Node.js, Mongo, or AWS Lambda.

STRICT FORMATTING RULES:
1. DO NOT start with "Act I" or "Episode X". Start directly with the hook.
2. Tone: Casual, slightly cynical but smart. "Thinking out loud."
3. Structure (Strictly follow these line breaks):
   - The Hook & The Meat: The story (1 solid paragraph). Start in the middle of the problem.
   - [INSERT 2 BLANK LINES HERE]
   - The Ending: "Moral of the story:" followed by a quirky, sarcastic, or witty one-liner.
   - [INSERT 2 BLANK LINES HERE]
   - The Footer: Exactly these hashtags: #backend #engineering #software #java

Length: Under 180 words.

Output JSON format: {{ "post_text": "...", "lesson_extracted": "..." }}
"""

    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        content = json.loads(response.text)
        save_json(DRAFT_FILE, content)
        print(f"Draft saved to {DRAFT_FILE}.")
        print("PREVIEW:")
        print(content["post_text"][:200] + "...")
    except Exception as e:
        print(f"Generation Failed: {e}")
        exit(1)


def run_publish_mode():
    print("STARTING PUBLISH MODE...")
    draft = load_json(DRAFT_FILE)
    if not draft:
        print("No draft found! Skipping publish.")
        exit(0)

    print("\nCONTENT TO POST:")
    print("-" * 20)
    print(draft["post_text"])
    print("-" * 20 + "\n")

    image_path = get_image_from_folder()
    if image_path:
        print(f"Found user image: {image_path}")
    else:
        print("No image found. Posting text only.")

    urn = get_user_urn()
    if not urn:
        print("CRITICAL: Could not get User URN. Check LinkedIn Token.")
        exit(1)

    media_urn = None
    media_id = None

    if image_path:
        media_urn, media_id = upload_image_to_linkedin(urn, image_path)
        if not media_urn:
            print("Image upload failed. Proceeding with text-only post.")
        else:
            # Poll until available
            available = poll_image_status(media_id, timeout_seconds=60, poll_interval=2)
            if not available:
                print("Image never became AVAILABLE. Proceeding with text-only post.")
                # Optionally: keep the uploaded image (do not remove), but post text-only
                media_urn = None

    # Attempt to post (with image_urn if available)
    success = post_to_linkedin(urn, draft["post_text"], image_asset=media_urn)

    if success:
        print("Published successfully.")

        state = load_json(STATE_FILE)
        if not state:
            state = {"act_index": 0, "episode": 1, "previous_lessons": []}

        state["previous_lessons"].append(draft.get("lesson_extracted", ""))
        state["episode"] += 1

        current_act = ACTS[state["act_index"]]
        if state["episode"] > current_act["max_episodes"]:
            state["act_index"] += 1
            state["episode"] = 1
            if state["act_index"] >= len(ACTS):
                state["act_index"] = 0

        save_json(STATE_FILE, state)

        try:
            os.remove(DRAFT_FILE)
        except Exception:
            pass

        # If image was used and exists in folder, remove it
        if image_path and media_urn:
            try:
                os.remove(image_path)
            except Exception:
                pass

        print("Cleanup complete.")
    else:
        print("Final Post Failed.")
        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()

    if args.mode == "draft":
        run_draft_mode()
    elif args.mode == "publish":
        run_publish_mode()
