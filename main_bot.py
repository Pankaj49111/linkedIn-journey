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

# Prioritized list of API versions to try (Newest -> Oldest)
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
# 🛡️ JVM FIREWALL
# =============================
FORBIDDEN_TECH_TERMS = [
    "node", "nodejs", "event loop", "goroutine", "golang", " go ",
    "python", "gil", "rust", ".net", "c#", "async await"
]

# =============================
# 🧠 MUTATION ENGINE
# =============================
PROMPT_MUTATIONS = {
    "NO_CONFUSION": """
    EDITOR REQUEST: Inject a moment of genuine uncertainty before the realization.
    Show the narrator misreading metrics, checking the wrong logs, or feeling puzzled.
    Do not explain the solution immediately. Make us feel the confusion.
    """,
    "CONTRADICTION_TOO_LATE": """
    EDITOR REQUEST: Move the 'Contradiction' earlier.
    The system behavior must defy expectation explicitly in the first half.
    "I expected X, but Y happened."
    """,
    "IMPACT_TOO_ABSTRACT": """
    EDITOR REQUEST: The consequences feel too theoretical.
    Replace abstract impact with CONCRETE operational pain:
    - PagerDuty escalation at 3 AM.
    - A forced rollback.
    - Customer support tickets piling up.
    - Massive technical debt accumulation.
    """,
    "TOO_EXPLANATORY": """
    EDITOR REQUEST: You are explaining like a textbook. Stop teaching.
    Replace diagnostic explanations with OBSERVATIONS.
    Show us what you saw, not how the technology works under the hood.
    """,
    "MORAL_TOO_DOC_LIKE": """
    EDITOR REQUEST: The moral sounds like documentation or generic advice.
    Rewrite the final sentence as a LIVED TRUTH.
    Use declarative language. No "Always", "Ensure", "Avoid".
    """,
    "NO_HUMILITY": """
    EDITOR REQUEST: You sound too perfect.
    Explicitly state the wrong assumption you made.
    Use phrases like "I assumed...", "It never occurred to me...", "I was convinced...".
    """,
    "MISSING_CONFESSION_KEYWORD": """
    CRITICAL STRUCTURE FAILURE: You missed the mandatory confession phrase.
    You MUST include a phrase like: "I assumed", "I thought", "It never occurred to me", "I was convinced".
    """,
    "MORAL_STRUCTURE_FAIL": """
    CRITICAL STRUCTURE FAILURE: The moral section is malformed.
    Ensure exactly ONE sentence appears after 'The Moral 👇'.
    """,
    "FORBIDDEN_TERM": """
    CRITICAL FAILURE: You used a forbidden term (Node, Go, Python, etc.).
    This account is strictly JVM/Backend engineering.
    Rewrite entirely using JVM terminology (Thread Pools, GC, Heap) or generic systems terms.
    """
}

# =============================
# NARRATIVE SPINES
# =============================
NARRATIVE_SPINES = {
    "CLASSIC_FAILURE": {
        "weight": 55,
        "instructions": """
        1. Identity & humility
        2. Confident decision
        3. Real-world trigger (Traffic spike/Alert)
        4. Failure symptoms (The crash)
        5. CONTRADICTION (Why did it fail?)
        6. INFLECTION (Realization)
        7. LESSON (Correction)
        """
    },
    "SILENT_FAILURE": {
        "weight": 25,
        "instructions": """
        1. Identity & humility
        2. Confident decision
        3. GREEN METRICS (System looked healthy)
        4. The nagging feeling / subtle anomaly
        5. The delayed discovery (Weeks later - Data corruption/Debt)
        6. INFLECTION (The invisible cost realized)
        7. LESSON (Integrity/Observability)
        CRITICAL: No alerts fired. No incident declared. The damage was silent.
        """
    },
    "SCARY_SUCCESS": {
        "weight": 20,
        "instructions": """
        1. Identity & humility
        2. The high-stakes change (Scaling/Infra)
        3. IMMEDIATE SUCCESS (Metrics improved, Team cheered)
        4. The hollow feeling / uneasiness
        5. CONTRADICTION (Success hid a new fragility)
        6. INFLECTION (Realization of risk)
        7. LESSON (Fragility/Complexity)
        """
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
            "act_index": 0, "episode": 1,
            "previous_lessons": [], "last_themes": [], "last_tech": [], "last_spines": []
        }
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {
            "act_index": 0, "episode": 1,
            "previous_lessons": [], "last_themes": [], "last_tech": [], "last_spines": []
        }

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def clean_text(text, forbidden_phrases=None):
    if not text: return ""
    text = text.replace("*", "")
    text = re.sub(r'(?i)^(Hook|Lesson|Reflection|Post|Body):', '', text, flags=re.MULTILINE)
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
    """Logs failed drafts for future training/prompt refinement."""
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

# 🔧 API RETRY HANDLER WITH SAFETY CHECK
def generate_safe(client, prompt, model="gemini-flash-latest", temperature=0.7):
    max_retries = 3
    base_delay = 5

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=temperature
    )

    for i in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config
            )

            try:
                if not response.text:
                    raise ValueError("Blocked by Safety Filter (Empty response)")
            except Exception:
                raise ValueError("Blocked by Safety Filter (Invalid response object)")

            return response

        except Exception as e:
            error_msg = str(e).lower()
            wait_time = base_delay * (2 ** i)

            if "blocked" in error_msg or "safety" in error_msg:
                safe_print(f"🛡️ Safety Filter Triggered. Retrying with higher temp... ({i+1}/{max_retries})")
                temperature = min(1.0, temperature + 0.2)
                config = types.GenerateContentConfig(response_mime_type="application/json", temperature=temperature)

            elif "503" in error_msg or "overloaded" in error_msg:
                safe_print(f"⚠️ API Overloaded. Retrying in {wait_time}s... ({i+1}/{max_retries})")

            else:
                safe_print(f"⚠️ API Error: {e}. Retrying...")

            time.sleep(wait_time)

    raise Exception("❌ API failed after max retries.")

# 🔧 1. DETERMINISTIC PRE-FLIGHT CHECK
def structural_precheck(post):
    confession_pattern = r"\b(I (assumed|thought|was certain|expected|guessed)|It never occurred to me|I was convinced)\b"

    if not re.search(confession_pattern, post, re.IGNORECASE):
        return False, "MISSING_CONFESSION_KEYWORD"

    if "The Moral 👇" not in post:
        return False, "MORAL_STRUCTURE_FAIL"

    moral_part = post.split("The Moral 👇")[-1].strip()
    if moral_part.count(".") > 1:
        segments = [s for s in moral_part.split(".") if len(s.strip()) > 2]
        if len(segments) > 1:
            return False, "MORAL_STRUCTURE_FAIL"

    return True, None

# 🔧 2. FORMATTING ENGINE
def format_for_linkedin(text):
    text = text.replace('\r\n', '\n').strip()

    # Hook Isolation
    match = re.match(r'(.*?[.!?])(\s+)(.*)', text, re.DOTALL)
    if match:
        hook = match.group(1).strip()
        rest = match.group(3).strip()
        if len(hook) < 150:
            text = f"{hook}\n\n{rest}"

    # Paragraph Splitting
    raw_paragraphs = re.split(r'\n+', text)
    final_paragraphs = []

    for p in raw_paragraphs:
        p = p.strip()
        if not p: continue

        if p == final_paragraphs[0] if final_paragraphs else False:
            final_paragraphs.append(p)
            continue

        if len(p) > 250:
            sentences = re.split(r'(?<=[.!?]) +', p)
            chunk = ""
            count = 0
            for s in sentences:
                chunk += s + " "
                count += 1
                if count >= 2:
                    final_paragraphs.append(chunk.strip())
                    chunk = ""
                    count = 0
            if chunk: final_paragraphs.append(chunk.strip())
        else:
            final_paragraphs.append(p)

    return "\n\n".join(final_paragraphs)

def enforce_single_moral(text):
    if "The Moral 👇" not in text:
        return text
    parts = text.split("The Moral 👇")
    body = parts[0]
    moral_section = parts[1].strip()

    first_sentence_match = re.match(r'(.*?[.!?])', moral_section, re.DOTALL)

    if first_sentence_match:
        clean_moral = first_sentence_match.group(1).strip()
        return f"{body.strip()}\n\nThe Moral 👇\n\n{clean_moral}"
    else:
        clean_moral = moral_section.split('\n')[0].strip()
        return f"{body.strip()}\n\nThe Moral 👇\n\n{clean_moral}"

# =============================
# LOGIC
# =============================
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
    if not available_spines:
        available_spines = list(NARRATIVE_SPINES.keys())

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
    Just let the wisdom inform your current reaction.
    """

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
        if file.lower().endswith(valid_extensions):
            return os.path.join(IMAGE_FOLDER, file)
    return None

def upload_image_to_linkedin(urn, image_path):
    safe_print("Uploading image...")
    init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
    payload = {"initializeUploadRequest": {"owner": f"urn:li:person:{urn}"}}

    # Self-Healing Version Loop for Image Upload
    for version in LINKEDIN_VERSIONS_FALLBACK:
        headers = {
            'Authorization': f'Bearer {LINKEDIN_TOKEN}',
            'Content-Type': 'application/json',
            'LinkedIn-Version': version,
            'X-Restli-Protocol-Version': '2.0.0'
        }

        try:
            resp = requests.post(init_url, headers=headers, json=payload, timeout=30)

            # If 426, retry next version
            if resp.status_code == 426:
                safe_print(f"⚠️ Image Upload: Version {version} inactive. Retrying...")
                continue

            # If unexpected error
            if resp.status_code != 200:
                safe_print(f"❌ Image Init Failed [{resp.status_code}]: {resp.text}")
                continue

            # Success
            data = resp.json().get('value') or resp.json()
            upload_url = data.get('uploadUrl')
            image_urn = data.get('image') or data.get('imageUrn')

            if not upload_url:
                safe_print(f"❌ Upload URL missing in response.")
                return None

            # Perform Binary Upload
            with open(image_path, 'rb') as f:
                requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=f, timeout=60)

            return image_urn

        except Exception as e:
            safe_print(f"❌ Image Upload Exception: {e}")
            continue

    safe_print("❌ All LinkedIn versions failed for image upload.")
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
            # If 426 on polling, we might need to fallback too, but usually unnecessary for GET
            if resp.status_code == 426:
                headers["LinkedIn-Version"] = LINKEDIN_VERSIONS_FALLBACK[1] # Try one older
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

# 🛠️ SELF-HEALING POST FUNCTION
def post_to_linkedin(urn, text, image_asset=None):
    text = format_for_linkedin(text)
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

    # Self-Healing Version Loop
    for version in LINKEDIN_VERSIONS_FALLBACK:
        headers = {
            "Authorization": f"Bearer {LINKEDIN_TOKEN}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": version
        }

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
Review the post below.

If multiple failures exist, select ONLY the most dominant one blocking PASS.

FAIL if:
1. No explicit wrong belief admitted.
2. No genuine confusion.
3. Impact is abstract.
4. Tone is explanatory/teaching.
5. Moral feels like documentation.

IMPORTANT: Prefer narrowly scoped, incident-specific realizations over generalized system truths.
Senior writing captures the incident. Staff+ writing generalizes too much. Stay Senior.

OUTPUT JSON ONLY:
{
  "verdict": "PASS_9_PLUS" OR "FAIL",
  "failure_axis": "NO_CONFUSION" | "CONTRADICTION_TOO_LATE" | "IMPACT_TOO_ABSTRACT" | "TOO_EXPLANATORY" | "MORAL_TOO_DOC_LIKE" | "NO_HUMILITY",
  "editor_note": "Reason"
}
"""

def build_prompt(act, episode, theme, tech, prev_lessons, spine_instructions, act_index, echo_instruction):
    payoff_instruction = get_arc_payoff(act_index)

    return f"""
Role:
You are a Senior Backend Engineer (JAVA/JVM focused) reflecting on a real production experience.

INVISIBLE CONTEXT:
- Life Stage: {act['name']} (Episode {episode})
- Theme: {theme['type']}
- Tech Focus: {tech}

PREVIOUSLY LEARNED (Do not repeat):
{prev_lessons}

MANDATORY NARRATIVE SPINE:
{spine_instructions}

{payoff_instruction}
{echo_instruction}

[[EDITOR_FEEDBACK_SLOT]]

CONFESSION RULE:
State your wrong assumption naturally (e.g., "I thought...", "I assumed...", "It never occurred to me...").

STYLE RULES:
- No paragraph > 2 lines
- Active voice
- First 2 lines = hook (≤10 words)
- Emojis: Strict Limit 3-5.
- Stay inside the moment; no retrospectives.
- Include one concrete human or operational consequence.

STRICT FORMAT:
- End the post EXACTLY after the Moral sentence.
- Moral must be DECLARATIVE statements of truth.
- Avoid absolute generalizations. Keep scope local to the incident.
- Format:
  "The Moral 👇"
  [One sharp sentence]
  [STOP WRITING HERE]

OUTPUT JSON ONLY:
{{
  "post_text": "...",
  "lesson_extracted": "One uncomfortable lesson in one sentence"
}}
Length: 150–200 words
"""

# =============================
# MUTATION LOOP (Convergent)
# =============================
def generate_with_review(client, base_prompt, forbidden_phrases):
    last_content = None
    feedback_text = ""
    previous_axis = None

    MAX_ATTEMPTS = 4

    for attempt in range(MAX_ATTEMPTS):
        safe_print(f"🔄 Generation Attempt {attempt + 1}")

        temp = 0.7 if attempt == 0 else 0.4
        current_prompt = base_prompt.replace("[[EDITOR_FEEDBACK_SLOT]]", feedback_text)

        try:
            response = generate_safe(client, current_prompt, temperature=temp)
            content = json.loads(response.text)

            # This handles both cleaning AND Forbidden Term checks
            post = clean_text(content["post_text"], forbidden_phrases)

            content["post_text"] = post
            last_content = content

            passed_structure, failure_axis = structural_precheck(post)
            if not passed_structure:
                safe_print(f"❌ Pre-flight Check Failed: {failure_axis}")
                if attempt < MAX_ATTEMPTS - 1:
                    mutation = PROMPT_MUTATIONS.get(failure_axis, "Fix structure.")
                    feedback_text = f"\n--- CRITICAL FEEDBACK ---\n{mutation}"
                    continue

            judge_resp = generate_safe(client, f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{post}", temperature=0.1)
            raw_judge = judge_resp.text.replace("```json", "").replace("```", "").strip()
            verdict_data = json.loads(raw_judge)

            safe_print(f"🕵️ Verdict: {verdict_data.get('verdict')} | Axis: {verdict_data.get('failure_axis')}")

            if verdict_data.get("verdict") == "PASS_9_PLUS":
                return content

            axis = verdict_data.get("failure_axis", "NO_HUMILITY")
            if axis == previous_axis:
                safe_print("⚠️ Same failure axis repeated. Stopping mutation to preserve authenticity.")
                return content

            previous_axis = axis
            mutation = PROMPT_MUTATIONS.get(axis, PROMPT_MUTATIONS["NO_HUMILITY"])
            safe_print(f"💉 Injecting Mutation: {axis}")
            feedback_text = f"\n--- EDITOR FEEDBACK ---\n{mutation}\nTASK: Rewrite the story applying this fix."

        except ValueError as ve:
            # Handle Forbidden Terms (Go, Node, etc.)
            safe_print(f"🚫 {ve}")
            if attempt < MAX_ATTEMPTS - 1:
                feedback_text = f"\n--- CRITICAL FEEDBACK ---\n{PROMPT_MUTATIONS['FORBIDDEN_TERM']}"
                continue
            else:
                safe_print("❌ Failed due to Forbidden Term on last attempt.")
                sys.exit(1)

        except (json.JSONDecodeError, Exception) as e:
            safe_print(f"⚠️ Generation Issue: {e}. Retrying...")
            continue

    safe_print("⚠️ Quality Gate failed after max attempts. Soft landing initiated.")

    if last_content:
        log_failure(last_content["post_text"], previous_axis, verdict_data.get("editor_note", "Max attempts"))
        return last_content

    safe_print("❌ Critical Failure: No content generated.")
    sys.exit(1)

# =============================
# MODES
# =============================
def run_draft_mode():
    state = load_json(STATE_FILE)
    client = genai.Client(api_key=GEMINI_KEY)

    act = ACTS[state["act_index"]]
    theme, tech = select_theme_and_tech(state)
    prev = "\n".join(f"- {l}" for l in state["previous_lessons"][-5:])

    spine_name, spine_steps = select_spine(state)
    echo_instr = maybe_add_deferred_echo(state)

    print("\n" + "="*40)
    safe_print(f"🎭 ACT:   {act['name']}")
    safe_print(f"🦴 SPINE: {spine_name}")
    safe_print(f"🎰 THEME: {theme['type']}")
    safe_print(f"🛠️ TECH:  {tech}")
    print("="*40 + "\n")

    base_prompt = build_prompt(act, state["episode"], theme, tech, prev, spine_steps, state["act_index"], echo_instr)
    forbidden = [act["name"], theme["type"]] + [t["type"] for t in THEMES]

    content = generate_with_review(client, base_prompt, forbidden)
    content["meta_theme"] = theme["type"]
    content["meta_tech"] = tech
    content["meta_spine"] = spine_name

    content["post_text"] = format_for_linkedin(content["post_text"])
    content["post_text"] = enforce_single_moral(content["post_text"])

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
    state["previous_lessons"].append(draft["lesson_extracted"])
    state.setdefault("last_themes", []).append(draft["meta_theme"])
    state.setdefault("last_tech", []).append(draft["meta_tech"])
    state.setdefault("last_spines", []).append(draft["meta_spine"])

    state["last_themes"] = state["last_themes"][-5:]
    state["last_tech"] = state["last_tech"][-5:]
    state["last_spines"] = state["last_spines"][-2:]

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