import os
import json
import argparse
import requests
import google.generativeai as genai
import sys

# Force UTF-8 for logs to prevent crashes with emojis
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

# --- HELPERS (Now with UTF-8 Enforcement) ---
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
        print("⚠️ No draft found! Skipping publish.")
        exit(0)

    # --- DEBUG PRINT: What are we actually posting? ---
    print("\n📝 CONTENT TO POST:")
    print("-" * 20)
    print(draft["post_text"])
    print("-" * 20 + "\n")

    image_path = get_image_from_folder()
    if image_path: print(f"📸 Found user image: {image_path}")
    else: print("📝 No image found. Posting text only.")

    urn = get_user_urn()
    if not urn:
        print("❌ CRITICAL: Could not get User URN. Check LinkedIn Token.")
        exit(1)

    media_urn = None
    if image_path:
        media_urn = upload_image_to_linkedin(urn, image_path)
        if not media_urn:
            print("⚠️ Image upload failed. Proceeding with TEXT ONLY.")

    # Post to LinkedIn
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
        resp = requests.post(init_url, headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"❌ Init Upload Error: {resp.status_code} - {resp.text}")
            return None
        
        data = resp.json()['value']
        upload_url = data['uploadUrl']
        image_urn = data['image']
        
        with open(image_path, 'rb') as f:
            put_resp = requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f)
            if put_resp.status_code not in [200, 201]:
                print(f"❌ Binary Upload Error: {put_resp.status_code} - {put_resp.text}")
                return None
                
        return image_urn
    except Exception as e:
        print(f"❌ Upload Exception: {e}")
        return None

def post_to_linkedin(urn, text, image_asset=None):
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION
    }
    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }
    if image_asset:
        payload["content"] = {"media": {"title": "Tech Insight", "id": image_asset}}

    resp = requests.post(url, headers=headers, json=payload)
    
    if resp.status_code != 201:
        print(f"❌ Post Creation Error: {resp.status_code} - {resp.text}")
        
    return resp.status_code == 201

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()

    if args.mode == "draft": run_draft_mode()
    elif args.mode == "publish": run_publish_mode()