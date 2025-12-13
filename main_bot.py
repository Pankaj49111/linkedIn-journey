import os
import json
import argparse
import requests
import google.generativeai as genai

# --- CONFIGURATION ---
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

# Files
STATE_FILE = "story_state.json"
DRAFT_FILE = "current_draft.json"
IMAGE_FOLDER = "images"  # Folder to look for images

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
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def get_image_from_folder():
    """Checks the images/ folder for any valid image file"""
    if not os.path.exists(IMAGE_FOLDER):
        return None
    
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(IMAGE_FOLDER):
        if file.lower().endswith(valid_extensions):
            return os.path.join(IMAGE_FOLDER, file)
    return None

# --- CORE LOGIC ---

def run_draft_mode():
    """Morning: Generates text and saves to draft file."""
    print("🌅 STARTING DRAFT MODE...")
    
    # 1. Load current state (to know which Episode we are on)
    state = load_json(STATE_FILE)
    if not state:
        state = {"act_index": 0, "episode": 1, "previous_lessons": []}

    # 2. Configure Gemini
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-flash-latest")

    act = ACTS[state["act_index"]]
    previous_lessons = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    # 3. Generate Content
    prompt = f"""
    Role: You are a Senior Backend Engineer sharing a raw, authentic story.
    
    Current Life Stage: {act['name']} (Episode {state['episode']})
    Context: {previous_lessons}
    
    STRICT TECH STACK: Java 17/21, Spring Boot, Hibernate, Postgres, Cassandra, Redis, Kafka, Docker, K8s.
    
    STRICT FORMATTING RULES:
    1. DO NOT start with "Act I". Start with the Hook.
    2. Tone: Casual, cynical, smart.
    3. Structure: Hook/Story -> (2 Blank Lines) -> Moral (Quirky) -> (2 Blank Lines) -> Hashtags.
    4. Hashtags: #backend #engineering #software #java
    
    OUTPUT JSON: {{ "post_text": "...", "lesson_extracted": "..." }}
    """
    
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        content = json.loads(response.text)
        
        # 4. Save to Draft File (Do NOT update state yet)
        save_json(DRAFT_FILE, content)
        print(f"✅ Draft saved to {DRAFT_FILE}. Ready for review/image.")
        
    except Exception as e:
        print(f"❌ Generation Failed: {e}")
        exit(1)

def run_publish_mode():
    """Evening: Reads draft, checks image, posts to LinkedIn."""
    print("🚀 STARTING PUBLISH MODE...")
    
    # 1. Load Draft
    draft = load_json(DRAFT_FILE)
    if not draft:
        print("⚠️ No draft found! Skipping publish.")
        exit(0) # Not an error, just nothing to do

    # 2. Check for Image
    image_path = get_image_from_folder()
    if image_path:
        print(f"📸 Found user image: {image_path}")
    else:
        print("📝 No image found. Posting text only.")

    # 3. Get LinkedIn User
    urn = get_user_urn()
    if not urn:
        print("❌ Invalid LinkedIn Token")
        exit(1)

    # 4. Upload Image (If exists)
    media_urn = None
    if image_path:
        media_urn = upload_image_to_linkedin(urn, image_path)
    
    # 5. Post to LinkedIn
    success = post_to_linkedin(urn, draft["post_text"], media_urn)
    
    if success:
        print("✅ Published successfully!")
        
        # 6. UPDATE STATE (Only now do we advance the episode)
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
        
        # 7. Cleanup (Delete draft and image so we don't repost tomorrow)
        os.remove(DRAFT_FILE)
        if image_path:
            os.remove(image_path)
        print("🧹 Cleanup complete.")
        
    else:
        print("❌ Failed to post.")
        exit(1)

# --- LINKEDIN UTILS ---
def get_user_urn():
    try:
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
        resp = requests.get(url, headers=headers)
        return resp.json().get("sub")
    except: return None

def upload_image_to_linkedin(urn, image_path):
    print("Uploading image...")
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    headers = {
        'Authorization': f'Bearer {LINKEDIN_TOKEN}',
        'Content-Type': 'application/json',
        'LinkedIn-Version': '202401',
        'X-Restli-Protocol-Version': '2.0.0'
    }
    payload = {"initializeUploadRequest": {"owner": f"urn:li:person:{urn}"}}
    try:
        resp = requests.post(init_url, headers=headers, json=payload)
        if resp.status_code != 200: return None
        data = resp.json()['value']
        with open(image_path, 'rb') as f:
            requests.put(data['uploadUrl'], headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f)
        return data['image']
    except: return None

def post_to_linkedin(urn, text, image_asset=None):
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202401"
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
    return resp.status_code == 201

# --- ENTRY POINT ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True, help="Choose 'draft' to generate or 'publish' to post")
    args = parser.parse_args()

    if args.mode == "draft":
        run_draft_mode()
    elif args.mode == "publish":
        run_publish_mode()