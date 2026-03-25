import os
import json
import argparse
import requests
from google import genai
from google.genai import types
import sys
import time
import urllib.parse
import re
import random
from datetime import datetime

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
FAILED_DRAFTS_FILE = "failed_drafts.json"
IMAGE_FOLDER = "images"

# Prioritized list of API versions
LINKEDIN_VERSIONS_FALLBACK = [
    "202511", "202510", "202509", "202508", "202507", "202506",
    "202505", "202504", "202503", "202502", "202501",
    "202412", "202411", "202410", "202409", "202408", "202407", "202406", "202401"
]

# --- PERSONAL BRANDING ---
MY_NAME = "Pankaj Kumar"

FIXED_CTA = f"""
♻️ Repost to save someone from learning this the hard way.

➕ Follow {MY_NAME} for backend engineering lessons earned in production.
"""

FIXED_HASHTAGS = "\n\n#backend #engineering #software #java"

# =============================
# 🎭 POST MODES (Rebalanced)
# =============================
POST_MODES = {
    "FAILURE": 0.20,
    "QUIET_WIN": 0.25,
    "CONTRARIAN": 0.25,
    "TACTICAL": 0.20,
    "HUMAN": 0.10
}

# =============================
# 🧠 EMOTIONAL MUTEX LAYERS
# =============================
EMOTIONAL_LAYERS = ["DRIFT", "HOOK", "BREAKER", "NONE"]

# =============================
# 🛡️ JVM FIREWALL
# =============================
FORBIDDEN_TECH_TERMS = [
    "node", "nodejs", "event loop", "goroutine", "golang", " go ",
    "python", "gil", "rust", ".net", "c#", "async await"
]

# =============================
# 🌫️ HUMAN DRIFT ASSETS
# =============================
HUMAN_INTERRUPTS = [
    "I stared at the dashboard longer than I should have.",
    "I refreshed the logs again.",
    "Slack was quiet.",
    "I closed my laptop for a minute.",
    "Something felt off.",
    "I re-read the same metric twice."
]

FATIGUE_LINES = [
    "These days I don’t rush fixes.",
    "Earlier in my career I would have pushed harder.",
    "Now I slow down.",
    "I’ve learned to sit with uncertainty."
]

UNRESOLVED_ENDINGS = [
    "I still think about that.",
    "Production remembers.",
    "That wasn’t the end.",
    "We got lucky that time.",
    "That part stuck with me."
]

ENGAGEMENT_HOOKS = [
    "Most people stop thinking right here.",
    "This is where teams usually get comfortable.",
    "Almost nobody asks what happens next.",
    "That assumption costs more than latency.",
    "This is where production quietly disagrees.",
    "This sounds correct in theory."
]

BELIEF_BREAKERS = [
    "Scaling didn't fix it.",
    "The dashboard was lying.",
    "Latency wasn’t the problem.",
    "The system wasn’t slow. We were.",
    "Availability hid the failure.",
    "The architecture was fine. The assumptions weren’t.",
    "Nothing crashed. Everything degraded.",
    "The metrics were green. The system wasn’t."
]

# =============================
# 🧠 MUTATION ENGINE
# =============================
PROMPT_MUTATIONS = {
    "NO_CONFUSION": """
    EDITOR REQUEST: Inject a moment of genuine uncertainty before the realization.
    Show the narrator misreading metrics, checking the wrong logs, or feeling puzzled.
    """,
    "CONTRADICTION_TOO_LATE": """
    EDITOR REQUEST: Move the 'Contradiction' earlier.
    The system behavior must defy expectation explicitly in the first half.
    """,
    "IMPACT_TOO_ABSTRACT": """
    EDITOR REQUEST: The consequences feel too theoretical.
    Replace abstract impact with CONCRETE operational pain:
    - PagerDuty escalation at 3 AM.
    - A forced rollback.
    - Massive technical debt accumulation.
    """,
    "TOO_EXPLANATORY": """
    EDITOR REQUEST: You are explaining like a textbook. Stop teaching.
    Replace diagnostic explanations with OBSERVATIONS.
    Show us what you saw, not how the technology works under the hood.
    """,
    "MORAL_TOO_DOC_LIKE": """
    EDITOR REQUEST: The lesson sounds like documentation.
    Rewrite it as a LIVED TRUTH. Use declarative language.
    """,
    "NO_HUMILITY": """
    EDITOR REQUEST: You sound too perfect.
    Explicitly state the wrong assumption you made.
    Use phrases like "I assumed...", "It never occurred to me...".
    """,
    "MISSING_CONFESSION_KEYWORD": """
    CRITICAL STRUCTURE FAILURE: You missed the mandatory confession phrase.
    You MUST include a phrase like: "I assumed", "I thought", "It never occurred to me".
    """,
    "MORAL_STRUCTURE_FAIL": """
    CRITICAL STRUCTURE FAILURE: The lesson section is malformed.
    Ensure exactly ONE sentence appears after 'What I learned:'.
    """,
    "FORBIDDEN_TERM": """
    CRITICAL FAILURE: You used a forbidden term (Node, Go, Python, etc.).
    This account is strictly JVM/Backend engineering.
    Rewrite entirely using JVM terminology.
    """,
    "MODE_MISMATCH": """
    CRITICAL FAILURE: You failed to follow the requested MODE structure.
    Review the mode definition and rewrite.
    """
}

# =============================
# NARRATIVE SPINES
# =============================
NARRATIVE_SPINES = {
    "CLASSIC_FAILURE": {
        "weight": 55,
        "instructions": "Identity -> Confident decision -> Trigger -> Crash -> Contradiction -> Realization -> Lesson"
    },
    "SILENT_FAILURE": {
        "weight": 25,
        "instructions": "Identity -> Confident decision -> GREEN METRICS -> Nagging feeling -> Delayed discovery -> Invisible cost -> Lesson"
    },
    "SCARY_SUCCESS": {
        "weight": 20,
        "instructions": "Identity -> High-stakes change -> IMMEDIATE SUCCESS -> Hollow feeling -> Contradiction -> Realization of risk -> Lesson"
    }
}

ACTS = [
    {"name": "ACT I – Early Confidence & First Systems", "max_episodes": 8},
    {"name": "ACT II – Scaling Pressure & Hidden Complexity", "max_episodes": 10},
    {"name": "ACT III – Incidents, Failures, Reality", "max_episodes": 8},
    {"name": "ACT IV – Trade-offs & Simplification", "max_episodes": 6},
    {"name": "ACT V – Ownership, Leadership, People Systems", "max_episodes": 6},
    {"name": "ACT VI – Judgment, Restraint, Engineering Wisdom", "max_episodes": 6},
]

TECH_FOCUS_AREAS = {
    "distributed_data": ["Cassandra", "CQRS", "Schema Evolution"],
    "caching": ["Redis", "Cache Invalidation", "Distributed Locking"],
    "async": ["Kafka Consumer Lag", "Idempotency", "Event Ordering"],
    "infra": ["Kubernetes OOMs", "Cold Starts", "Connection Pooling"],
    "observability": ["Misleading Metrics", "Alert Fatigue", "SLIs/SLOs"],
    "ownership": ["API Contracts", "Dependency Drift", "Legacy Migrations"]
}

THEMES = [
    {"type": "THE ARCHITECTURAL TRAP", "allowed_tech": ["distributed_data", "caching", "async"]},
    {"type": "THE HUMAN ALGORITHM", "allowed_tech": ["ownership", "async", "observability"]},
    {"type": "THE CRASH", "allowed_tech": ["infra", "async", "caching"]},
    {"type": "THE FALSE FIX", "allowed_tech": ["caching", "infra"]},
    {"type": "THE METRIC LIE", "allowed_tech": ["observability"]},
    {"type": "THE OWNERSHIP GAP", "allowed_tech": ["ownership"]},
    {"type": "THE EUREKA MOMENT", "allowed_tech": ["distributed_data", "caching"]},
    {"type": "THE SILENT VICTORY", "allowed_tech": ["infra", "observability"]},
    {"type": "THE BORING STACK", "allowed_tech": ["distributed_data", "infra"]}
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
            "act_index": 0, "episode": 1,
            "previous_lessons": [], "last_themes": [], "last_tech": [], "last_spines": [], "last_modes": []
        }
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {
            "act_index": 0, "episode": 1,
            "previous_lessons": [], "last_themes": [], "last_tech": [], "last_spines": [], "last_modes": []
        }

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def clean_text(text, forbidden_phrases=None):
    if not text: return ""
    text = text.replace("*", "")
    text = re.sub(r'(?i)^(Hook|Lesson|Reflection|Post|Body|Context):', '', text, flags=re.MULTILINE)
    text = text.replace("```json", "").replace("```", "")

    # 🚨 JVM FIREWALL
    for term in FORBIDDEN_TECH_TERMS:
        if re.search(rf"\b{re.escape(term.strip())}\b", text, re.IGNORECASE):
            raise ValueError(f"Forbidden term detected: '{term.strip()}'")

    if forbidden_phrases:
        for phrase in forbidden_phrases:
            pattern = r'(?im)^\s*' + re.escape(phrase) + r'\s*$'
            text = re.sub(pattern, '', text)
    return text.strip()

def log_failure(post, axis, note):
    if not os.path.exists(FAILED_DRAFTS_FILE):
        failures = []
    else:
        try:
            with open(FAILED_DRAFTS_FILE, "r", encoding="utf-8") as f: failures = json.load(f)
        except: failures = []

    failures.append({
        "date": datetime.now().isoformat(),
        "axis": axis,
        "note": note,
        "post_snippet": post[:200]
    })
    save_json(FAILED_DRAFTS_FILE, failures[-50:])

# 🔧 API RETRY HANDLER
def generate_safe(client, prompt, model="gemini-flash-latest", temperature=0.7):
    max_retries = 3
    base_delay = 5
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=temperature)
    for i in range(max_retries):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            try:
                if not response.text: raise ValueError("Blocked by Safety Filter")
            except Exception: raise ValueError("Blocked by Safety Filter")
            return response
        except Exception as e:
            error_msg = str(e).lower()
            wait_time = base_delay * (2 ** i)
            if "blocked" in error_msg or "safety" in error_msg:
                safe_print(f"🛡️ Safety Filter. Retrying... ({i+1}/{max_retries})")
                temperature = min(1.0, temperature + 0.2)
                config = types.GenerateContentConfig(response_mime_type="application/json", temperature=temperature)
            elif "503" in error_msg or "overloaded" in error_msg:
                safe_print(f"⚠️ API Overloaded. Retrying... ({i+1}/{max_retries})")
            else:
                safe_print(f"⚠️ API Error: {e}. Retrying...")
            time.sleep(wait_time)
    raise Exception("❌ API failed after max retries.")

# 🔧 1. STRUCTURAL PRE-FLIGHT CHECK (MODE AWARE)
def structural_precheck(post, mode):
    confession_pattern = r"\b(I (assumed|thought|was certain|expected|guessed)|It never occurred to me|I was convinced)\b"

    if mode == "FAILURE":
        if not re.search(confession_pattern, post, re.IGNORECASE):
            return False, "MISSING_CONFESSION_KEYWORD"
        if "What I learned:" not in post:
            return False, "MORAL_STRUCTURE_FAIL"

    if mode == "HUMAN":
        # Hard jargon check for HUMAN mode
        tech_count = sum(1 for t in ["latency", "throughput", "cpu", "memory", "database", "kafka", "redis", "sharding"] if t in post.lower())
        if tech_count > 0:
            return False, "MODE_MISMATCH" # Strictly no technical jargon in Human mode

    if mode == "CONTRARIAN":
        if len(post.split()) > 200:
            return False, "MODE_MISMATCH"

    return True, None

# 🔧 2. FORMATTING ENGINE (Optimized for Scannability)
def format_for_linkedin(text):
    text = text.replace('\r\n', '\n').strip()

    raw_paragraphs = re.split(r'\n+', text)
    processed_paragraphs = []

    for p in raw_paragraphs:
        p = p.strip()
        if not p: continue

        # If a block is too thick (>120 chars) and has multiple sentences, safely break it up
        if len(p) > 120 and re.search(r'[.!?]\s+[A-Z]', p):
            # Safe split: Keeps punctuation, splits ONLY on space before a Capital Letter
            sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z\"\'\u201C])', p)

            chunk = []
            for s in sentences:
                chunk.append(s.strip())
                # Group max 2 sentences per block, or force 1 if it's a very long sentence
                if len(chunk) == 2 or len(s) > 100:
                    processed_paragraphs.append(" ".join(chunk))
                    chunk = []
            if chunk:
                processed_paragraphs.append(" ".join(chunk))
        else:
            processed_paragraphs.append(p)

    # Isolate the Hook (Ensure the first line stands alone for scroll-stopping)
    if processed_paragraphs and len(processed_paragraphs[0]) > 60:
        match = re.match(r'(.*?[.!?])\s+(.+)', processed_paragraphs[0], re.DOTALL)
        if match:
            processed_paragraphs[0] = match.group(1).strip()
            processed_paragraphs.insert(1, match.group(2).strip())

    return "\n\n".join(processed_paragraphs)

def enforce_single_moral(text):
    splitter = "What I learned:"
    if splitter not in text: return text

    parts = text.split(splitter)
    body = parts[0]
    moral_section = parts[1].strip()

    first_sentence_match = re.match(r'(.*?[.!?])', moral_section, re.DOTALL)
    if first_sentence_match:
        clean_moral = first_sentence_match.group(1).strip()
    else:
        clean_moral = moral_section.split('\n')[0].strip()

    return f"{body.strip()}\n\n{splitter}\n\n{clean_moral}"

# =============================
# LOGIC LAYERS
# =============================
def select_post_mode(state):
    last_modes = state.get("last_modes", [])
    available = [m for m in POST_MODES.keys() if m not in last_modes[-3:]]
    if not available: available = list(POST_MODES.keys())
    weights = [POST_MODES[m] for m in available]
    return random.choices(available, weights=weights, k=1)[0]

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

def select_spine(state):
    last_spines = state.get("last_spines", [])
    available_spines = [k for k in NARRATIVE_SPINES.keys() if k not in last_spines[-2:]]
    if not available_spines: available_spines = list(NARRATIVE_SPINES.keys())
    weights = [NARRATIVE_SPINES[k]["weight"] for k in available_spines]
    selected_key = random.choices(available_spines, weights=weights, k=1)[0]
    return selected_key, NARRATIVE_SPINES[selected_key]["instructions"]

def get_arc_payoff(act_index):
    if act_index <= 2: return ""
    return """
    LONG-TERM PAYOFF INSTRUCTION:
    You are now in a later stage of your career (Act IV+).
    - Admit a trade-off you knowingly accept today.
    - Acknowledge the solution is imperfect.
    - The moral should be about acceptance/restraint, not just optimization.
    """

def maybe_add_deferred_echo(state):
    if state["episode"] % 5 != 0: return ""
    if not state.get("previous_lessons"): return ""
    return """
    NARRATIVE DEPTH INSTRUCTION:
    Subtly echo a past mistake conceptually without restating it explicitly.
    Do NOT reference specific dates, post numbers, or "previous lessons".
    """

# 🌫️ LAYER 3: HUMAN DRIFT
def apply_human_drift(text):
    paragraphs = text.split("\n\n")
    # Micro-interruption (20%)
    if random.random() < 0.20 and len(paragraphs) > 3:
        insert_at = random.randint(1, min(3, len(paragraphs)-2))
        paragraphs.insert(insert_at, random.choice(HUMAN_INTERRUPTS))
    text = "\n\n".join(paragraphs)
    # Career fatigue (10%) - Guarded against Moral Header
    if random.random() < 0.10 and "What I learned:" not in text:
        text += "\n\n" + random.choice(FATIGUE_LINES)
    return text

# 🔥 LAYER 4: ATTENTION LOOP
def apply_engagement_hooks(text):
    if random.random() < 0.35:
        hook = random.choice(ENGAGEMENT_HOOKS)
        paragraphs = text.split('\n\n')
        if len(paragraphs) > 2:
            paragraphs.insert(-1, hook)
            text = "\n\n".join(paragraphs)
            safe_print(f"🔥 Applied Engagement Hook")
    return text

def apply_belief_break(text):
    if random.random() < 0.40:
        breaker = random.choice(BELIEF_BREAKERS)
        paragraphs = text.split("\n\n")
        if len(paragraphs) > 2:
            paragraphs.insert(1, breaker)
            text = "\n\n".join(paragraphs)
            safe_print(f"🧨 Applied Belief Break")
    return text

def apply_post_moral_echo(text):
    if random.random() < 0.10:
        text += "\n\n" + random.choice(UNRESOLVED_ENDINGS)
        safe_print("🧲 Applied Unresolved Ending")
    return text

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

def get_image_from_folder():
    if not os.path.exists(IMAGE_FOLDER): return None
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(IMAGE_FOLDER):
        if file.lower().endswith(valid_extensions): return os.path.join(IMAGE_FOLDER, file)
    return None

def upload_image_to_linkedin(urn, image_path):
    safe_print("Uploading image...")
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    payload = {"initializeUploadRequest": {"owner": f"urn:li:person:{urn}"}}
    for version in LINKEDIN_VERSIONS_FALLBACK:
        headers = {'Authorization': f'Bearer {LINKEDIN_TOKEN}', 'Content-Type': 'application/json', 'LinkedIn-Version': version, 'X-Restli-Protocol-Version': '2.0.0'}
        try:
            resp = requests.post(init_url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 426: continue
            if resp.status_code != 200:
                safe_print(f"❌ Image Init Failed [{resp.status_code}]")
                continue
            data = resp.json().get('value') or resp.json()
            upload_url = data.get('uploadUrl')
            image_urn = data.get('image') or data.get('imageUrn')
            if not upload_url: return None
            with open(image_path, 'rb') as f:
                requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f, timeout=60)
            return image_urn
        except Exception: continue
    return None

def poll_image_status(image_urn):
    if not image_urn: return False
    encoded_urn = urllib.parse.quote(image_urn)
    url = f"https://api.linkedin.com/rest/images/{encoded_urn}"
    headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}", "LinkedIn-Version": LINKEDIN_VERSIONS_FALLBACK[0], "X-Restli-Protocol-Version": "2.0.0"}
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 426:
                headers["LinkedIn-Version"] = LINKEDIN_VERSIONS_FALLBACK[5]
                continue
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
    text = format_for_linkedin(text)
    # Only enforce moral if it exists (mode dependent)
    text = enforce_single_moral(text)

    url = "https://api.linkedin.com/rest/posts"
    full_text = text.strip() + "\n\n" + FIXED_CTA.strip() + FIXED_HASHTAGS
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

    for version in LINKEDIN_VERSIONS_FALLBACK:
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0", "LinkedIn-Version": version}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 201:
                safe_print(f"✅ Published successfully (Version: {version})")
                return True
            if resp.status_code == 426:
                safe_print(f"⚠️ Version {version} inactive. Retrying...")
                continue
            safe_print(f"❌ LinkedIn Error [{resp.status_code}]: {resp.text}")
            return False
        except Exception as e:
            safe_print(f"❌ Network Error: {e}")
            return False
    safe_print("❌ All LinkedIn versions failed.")
    return False

# =============================
# JUDGE & PROMPT
# =============================
QUALITY_GATE_PROMPT = """
Role: Critical Staff+ Editor.
Review the post below based on its MODE.

FAIL if:
1. It feels like "Content Creation" (Tips, Tricks).
2. It uses Q&A labels ("Question:", "Answer:").
3. It gives advice ("You should...").
4. It names specific products (WhatsApp, Uber, etc.).
5. (FAILURE MODE) It lacks a confession ("I assumed...").
6. (CONTRARIAN MODE) It uses hedging language.
7. (HUMAN MODE) It uses technical jargon.

OUTPUT JSON ONLY:
{
  "verdict": "PASS_9_PLUS" OR "FAIL",
  "failure_axis": "NO_CONFUSION" | "CONTRADICTION_TOO_LATE" | "IMPACT_TOO_ABSTRACT" | "TOO_EXPLANATORY" | "MORAL_TOO_DOC_LIKE" | "NO_HUMILITY" | "MODE_MISMATCH",
  "editor_note": "Reason"
}
"""

def build_prompt_by_mode(mode, act, episode, theme, tech, prev_lessons, spine, act_index, echo):
    payoff_instruction = get_arc_payoff(act_index)

    # 🧱 MODE-SPECIFIC PROMPT BLOCKS
    if mode == "FAILURE":
        core_instruction = f"""
        MODE: FAILURE NARRATIVE
        THEME: {theme['type']}
        TECH: {tech}
        SPINE: {spine}
        
        TASK: Write a story about a specific production failure you caused.
        - Start with the wrong assumption.
        - Describe the crash.
        - End with a sharp lesson.
        - MUST use "What I learned:" header for the conclusion.
        """

    elif mode == "QUIET_WIN":
        core_instruction = f"""
        MODE: QUIET WIN (No Drama)
        TECH: {tech}
        
        TASK: Describe a boring design decision that aged well.
        Structure:
        1. A choice you made (boring/conservative).
        2. Why it felt controversial at the time.
        3. A future moment where it quietly saved the team.
        4. Reflection without grand moralizing.
        
        Tone: Calm, grounded.
        End with: "What I learned:" followed by one sentence.
        """

    elif mode == "CONTRARIAN":
        core_instruction = f"""
        MODE: CONTRARIAN OPINION
        TECH: {tech}
        
        TASK: Write a sharp opinion that challenges common engineering wisdom.
        Structure:
        - Assertion (Max 10 words). MUST be a strong claim. No hedging.
        - Why most engineers get this wrong.
        - A production observation backing you up.
        - End with a provocative close.
        
        Constraints: NO "What I learned:" header. Max 160 words.
        """

    elif mode == "TACTICAL":
        core_instruction = f"""
        MODE: TACTICAL INSIGHT
        TECH: {tech}
        
        TASK: Share a senior-level tactical insight.
        Format:
        - Short intro sentence.
        - 3 tight bullet points.
        
        Constraints: NO narrative. NO moral header. NO confession required. Max 120 words.
        """

    elif mode == "HUMAN":
        core_instruction = """
        MODE: HUMAN / LEADERSHIP
        
        TASK: Reflect on a non-technical engineering moment.
        Focus on: A hiring mistake, a design review conflict, or letting someone take ownership.
        
        Constraints: ZERO technical jargon (No Kafka, No Redis, No Latency).
        Reflective tone. NO moral header.
        """

    return f"""
Role: Senior Backend Engineer (Java/JVM).
CONTEXT: {act['name']} (Ep {episode})
PREVIOUSLY: {prev_lessons}
{payoff_instruction}
{echo}

{core_instruction}

STYLE RULES:
- Active voice.
- First 2 lines = hook.
- Emojis: Max 2.
- No "tips and tricks". Lived experience only.

FORMATTING:
- Optimize for LinkedIn mobile scrolling (lots of white space).
- Write in highly scannable, single-sentence or two-sentence paragraphs.
- NEVER write a paragraph with more than 2 sentences.
- USE DOUBLE NEWLINES between every thought.

OUTPUT JSON ONLY:
{{
  "post_text": "...",
  "lesson_extracted": "One sentence summary"
}}
Length: 150–200 words
"""

# =============================
# MUTATION LOOP (Convergent)
# =============================
def generate_with_review(client, base_prompt, forbidden_phrases, mode):
    last_content = None
    feedback_text = ""
    previous_axis = None
    MAX_ATTEMPTS = 4

    # 🚨 HUMAN Mode Specific Forbidden Words
    if mode == "HUMAN":
        forbidden_phrases += ["kafka", "redis", "latency", "throughput", "cpu", "memory", "sharding", "database"]

    for attempt in range(MAX_ATTEMPTS):
        safe_print(f"🔄 Generation Attempt {attempt + 1}")
        temp = 0.7 if attempt == 0 else 0.4
        current_prompt = base_prompt.replace("[[EDITOR_FEEDBACK_SLOT]]", feedback_text)

        try:
            response = generate_safe(client, current_prompt, temperature=temp)
            content = json.loads(response.text)
            post = clean_text(content["post_text"], forbidden_phrases)
            content["post_text"] = post
            last_content = content

            passed, failure_axis = structural_precheck(post, mode)
            if not passed:
                safe_print(f"❌ Pre-flight Check Failed: {failure_axis}")
                if attempt < MAX_ATTEMPTS - 1:
                    mutation = PROMPT_MUTATIONS.get(failure_axis, "Fix structure.")
                    feedback_text = f"\n--- CRITICAL FEEDBACK ---\n{mutation}"
                    continue

            judge_resp = generate_safe(client, f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{post}", temperature=0.1)
            raw_judge = judge_resp.text.replace("```json", "").replace("```", "").strip()
            verdict_data = json.loads(raw_judge)

            safe_print(f"🕵️ Verdict: {verdict_data.get('verdict')} | Axis: {verdict_data.get('failure_axis')}")

            if verdict_data.get("verdict") == "PASS_9_PLUS": return content

            axis = verdict_data.get("failure_axis", "NO_HUMILITY")
            if axis == previous_axis: return content
            previous_axis = axis
            mutation = PROMPT_MUTATIONS.get(axis, PROMPT_MUTATIONS["NO_HUMILITY"])
            feedback_text = f"\n--- EDITOR FEEDBACK ---\n{mutation}\nTASK: Rewrite the story applying this fix."

        except ValueError as ve:
            safe_print(f"🚫 {ve}")
            if attempt < MAX_ATTEMPTS - 1:
                feedback_text = f"\n--- CRITICAL FEEDBACK ---\n{PROMPT_MUTATIONS['FORBIDDEN_TERM']}"
                continue
            else: sys.exit(1)
        except Exception as e:
            safe_print(f"⚠️ Generation Issue: {e}. Retrying...")
            continue

    if last_content: return last_content
    sys.exit(1)

# =============================
# MODES
# =============================
def run_draft_mode():
    state = load_json(STATE_FILE)
    client = genai.Client(api_key=GEMINI_KEY)

    # 1. SELECT MODE
    mode = select_post_mode(state)

    # 2. SELECT CONTEXT (Conditional)
    if mode == "HUMAN":
        theme, tech = None, None
    elif mode == "FAILURE":
        theme, tech = select_theme_and_tech(state)
    else:
        # For QUIET_WIN, CONTRARIAN, TACTICAL we need tech context but no narrative theme
        _, tech = select_theme_and_tech(state)
        theme = None

    act = ACTS[state["act_index"]]
    prev = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    # 🛑 FIX: Compute spine ONLY if mode is FAILURE
    spine_steps = select_spine(state) if mode == "FAILURE" else None

    echo_instr = maybe_add_deferred_echo(state)

    print("\n" + "="*40)
    safe_print(f"🎭 MODE:  {mode}")
    if tech: safe_print(f"🛠️ TECH:  {tech}")
    if theme: safe_print(f"🎰 THEME: {theme['type']}")
    print("="*40 + "\n")

    base_prompt = build_prompt_by_mode(mode, act, state["episode"], theme, tech, prev, spine_steps, state["act_index"], echo_instr)

    forbidden = [act["name"]]
    if theme: forbidden.append(theme["type"])
    forbidden += [t["type"] for t in THEMES]

    content = generate_with_review(client, base_prompt, forbidden, mode)
    content["meta_mode"] = mode
    content["meta_theme"] = theme["type"] if theme else "N/A"
    content["meta_tech"] = tech if tech else "N/A"

    # APPLY LAYERS (Emotional Mutex + Post-Moral Logic)
    emotion = random.choice(EMOTIONAL_LAYERS)

    if emotion == "DRIFT":
        content["post_text"] = apply_human_drift(content["post_text"])
    elif emotion == "HOOK":
        content["post_text"] = apply_engagement_hooks(content["post_text"])
    elif emotion == "BREAKER":
        content["post_text"] = apply_belief_break(content["post_text"])

    content["post_text"] = format_for_linkedin(content["post_text"])
    content["post_text"] = enforce_single_moral(content["post_text"])

    # 🛑 FIX: Apply Echo ONLY if no other emotion triggered
    if emotion == "NONE":
        content["post_text"] = apply_post_moral_echo(content["post_text"])

    save_json(DRAFT_FILE, content)
    print("\n✅ DRAFT SAVED:")
    safe_print(content["post_text"][:150] + "...")

def run_publish_mode():
    draft = load_json(DRAFT_FILE)
    if not draft:
        safe_print("⚠️ No draft found.")
        return
    urn = get_user_urn()
    if not urn:
        safe_print("❌ Invalid LinkedIn token.")
        return

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
    if not success: return

    state = load_json(STATE_FILE)

    # 🚨 ONLY STORE LESSONS FOR NARRATIVE POSTS
    if draft.get("meta_mode") in ["FAILURE", "QUIET_WIN"]:
        state["previous_lessons"].append(draft["lesson_extracted"])

    state.setdefault("last_modes", []).append(draft.get("meta_mode", "FAILURE"))
    state["last_modes"] = state["last_modes"][-5:]

    if draft.get("meta_theme") != "N/A":
        state.setdefault("last_themes", []).append(draft["meta_theme"])
        state["last_themes"] = state["last_themes"][-5:]

    if draft.get("meta_tech") != "N/A":
        state.setdefault("last_tech", []).append(draft["meta_tech"])
        state["last_tech"] = state["last_tech"][-5:]

    state["episode"] += 1
    if state["episode"] > ACTS[state["act_index"]]["max_episodes"]:
        state["episode"] = 1
        state["act_index"] = (state["act_index"] + 1) % len(ACTS)

    save_json(STATE_FILE, state)
    os.remove(DRAFT_FILE)
    if image_path: os.remove(image_path)
    safe_print("🚀 Published successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "publish"], required=True)
    args = parser.parse_args()
    if args.mode == "draft": run_draft_mode()
    elif args.mode == "publish": run_publish_mode()