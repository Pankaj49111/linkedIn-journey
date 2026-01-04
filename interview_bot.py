import os
import json
import argparse
import requests
from google import genai
import sys
import random
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

HISTORY_FILE = "interview_history.json"
STATE_FILE = "interview_state.json"

LINKEDIN_API_VERSION = "202411"

FIXED_HASHTAGS = "\n\n#backend #engineering #interviews #java #systemsdesign #jvm"

INTERVIEW_TOPICS = {
    "relational_db": [
        "Isolation levels breaking financial correctness",
        "Connection pools masking slow queries",
        "Indexes accelerating reads while killing writes",
        "Long transactions holding invisible locks"
    ],
    "nosql_misuse": [
        "Eventual consistency leaking into user workflows",
        "Hot partitions created by innocent keys",
        "Compaction pauses mistaken for traffic spikes"
    ],
    "derived_stores": [
        "Dual writes without atomicity",
        "Search indexes lagging behind truth",
        "Backfills causing production brownouts"
    ],
    "kafka": [
        "Ordering guarantees vs Consumer Group rebalances",
        "The myth of 'Exactly Once' in distributed systems",
        "Consumer lag: Latency vs Throughput trade-off"
    ],
    "redis": [
        "Using Redis as a primary database (The Persistence Trap)",
        "Distributed locks: The Clock Skew problem",
        "Eviction policies silently killing business logic"
    ],
    "jvm_mechanics": [
        "Thread Pool Exhaustion vs CPU saturation",
        "Stop-the-world GC pauses vs Network Latency",
        "JVM Warm-up: Why autoscaling is slow"
    ]
}

FORBIDDEN_TECH_TERMS = [
    "node", "nodejs", "event loop", "goroutine", "golang",
    "python", "gil", "rust", ".net", "c#", "async await"
]

ANSWER_LENSES = [
    "Failure Mode (How it breaks)",
    "Operational Cost (How it wakes us up)",
    "Scaling Edge Case (What happens at 10x)",
    "Human Assumption (What we forgot to ask)"
]

OPENING_POSTURES = [
    "A neutral observation ('It is common to see...')",
    "A mild contradiction ('We often assume X, but...')",
    "A quiet doubt ('I tend to pause when...')"
]

SERIES_MARKERS = [
    "One pattern I’ve noticed in senior interviews...",
    "This comes up more often than people expect...",
    "I tend to pause when this answer sounds complete..."
]

# =============================
# HELPERS
# =============================
def safe_print(text):
    try:
        print(text.encode("utf-8", "replace").decode("utf-8"))
    except Exception:
        print("Output scrubbed.")

def load_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def clean_text(text):
    if not text: return ""
    text = text.replace("*", "")

    # 1. JVM FIREWALL CHECK
    for term in FORBIDDEN_TECH_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
            raise ValueError(f"Forbidden non-JVM term detected: {term}")

    # 2. HEADER STRIPPER
    text = re.sub(r'(?i)^(Hook|Lesson|Insight|Signal|Trap|Reality|Common Answer|Where it breaks|Where it holds|Context|Observation):', '', text, flags=re.MULTILINE)

    # 3. FORCE PARAGRAPH SPACING
    text = re.sub(r'(?<!\n)\n(?!\n)', '\n\n', text)

    return text.strip()

def check_length_constraint(text):
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if len(s.strip()) > 3]
    if len(sentences) > 8: return False, len(sentences)
    return True, len(sentences)

def parse_json_safely(raw_text):
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        try:
            cleaned_lines = cleaned.replace('\n', '\\n')
            return json.loads(cleaned_lines, strict=False)
        except:
            return {"post_text": raw_text}

def select_topic(state):
    last_topics = state.get("last_topics", [])
    last_categories = state.get("last_categories", [])
    categories = list(INTERVIEW_TOPICS.keys())

    available_categories = [c for c in categories if c not in last_categories]
    if not available_categories: available_categories = categories
    category = random.choice(available_categories)

    # Bias against recent topics
    subtopics = INTERVIEW_TOPICS[category]
    available_subtopics = [t for t in subtopics if t not in last_topics]
    if not available_subtopics: available_subtopics = subtopics
    subtopic = random.choice(available_subtopics)

    return category, subtopic

def get_user_urn():
    try:
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200: return None
        return resp.json().get("sub")
    except Exception: return None

def post_to_linkedin(urn, text):
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION
    }

    full_text = text.strip() + FIXED_HASHTAGS
    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": full_text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    return resp.status_code == 201

def build_prompt(category, subtopic, lens, posture, use_series_marker, use_early_fail):

    # 1. Handle Series Marker Logic
    opening_instr = f"Start with: {posture}"
    if use_series_marker:
        marker = random.choice(SERIES_MARKERS)
        opening_instr = f"Start EXPLICITLY with this phrase: '{marker}'"

    # 2. Handle Structure Rotation (Standard vs Early Fail)
    if use_early_fail:
        structure_instr = """
        1. THE OBSERVATION: Describe the confident answer.
        2. THE EARLY CRACK: Don't wait. Immediately hint at the failure mode in paragraph 2.
        3. THE DEEP CONSEQUENCE: Expand on the operational cost and END with the 'Reveal Sentence'.
        """
    else:
        structure_instr = """
        1. THE OBSERVATION: Describe the standard, confident answer.
        2. THE CONTEXT: Briefly acknowledge where this mental model works (steady state).
        3. THE GAP & JUDGMENT: Describe the failure mode, and END with the 'Reveal Sentence'.
        """

    return f"""
Role:
You are a Senior Backend Engineer reflecting on patterns you've seen in interviews and production.

CONTEXT:
- Topic: {category}
- Specific Pattern: {subtopic}
- ANALYSIS LENS: {lens}
- OPENING INSTRUCTION: {opening_instr}

STRICT CONSTRAINTS:
1. JVM ONLY: All examples must be explainable within a JVM-based backend system.
2. NO PROPER NOUN SPAM: Use max 1 specific tool name (e.g. "Hibernate"). Prefer generic terms like "ORM", "Client", "Broker".
3. NO EMOJIS.

TASK:
Write a short, narrative observation (3 paragraphs).

NARRATIVE FLOW:
{structure_instr}

THE REVEAL SENTENCE (CRITICAL):
- The final sentence must NOT be academic.
- Follow this rhythm: "This is usually where the discussion stops being about [Concept] and starts revealing how someone reasons about [Pressure/Risk/Systems]."

STRICT FORMATTING:
- Use DOUBLE NEWLINES between every paragraph.
- MAX 3 SENTENCES per paragraph.
- MAX 8 SENTENCES TOTAL.
- JSON Output must escape newlines (use \\n).

OUTPUT JSON ONLY:
{{
  "post_text": "..."
}}
"""

def build_compress_prompt(original_text):
    return f"""
Role: Senior Editor.
Task: Compress the following text to increase density and seniority.

INPUT TEXT:
"{original_text}"

RULES:
1. Reduce sentence count to strictly 7 or 8 total.
2. Ensure there are exactly 3 paragraphs.
3. Remove any "teaching" or "explaining" fluff.
4. Keep the tone observational ("I see this"), not instructional ("You should").
5. The final sentence MUST be the "Reveal Sentence" about engineering judgment.
6. NO EMOJIS.

OUTPUT JSON ONLY:
{{
  "post_text": "..."
}}
"""

QUALITY_GATE_PROMPT = """
Role: Senior Engineer Peer (Java/JVM Context).

FAIL if:
- Post references non-JVM tech.
- Post uses headers or labels.
- Post uses emojis.
- Tone is academic ("holistic reasoning").
- Total length > 8 sentences.

PASS if:
- Tone is observational ("I've noticed...").
- Structure is 3 short, separated paragraphs.
- Final sentence connects technical gap to judgment.

Respond with exactly:
PASS or FAIL
"""

def generate_with_review(client, prompt):
    for attempt in range(2):
        safe_print(f"🔄 Generation Attempt {attempt + 1}")

        # 1. GENERATE DRAFT 1
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        content = parse_json_safely(response.text)

        try:
            draft1 = clean_text(content.get("post_text", ""))
        except ValueError as e:
            safe_print(f"⚠️ JVM Firewall Triggered: {e}")
            prompt += f"\nERROR: Forbidden term ({e}). Stick strictly to Java/JVM."
            continue

        # 2. AUTO-COMPRESS (DRAFT 2)
        safe_print("🔨 Running Auto-Compressor...")
        compress_resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=build_compress_prompt(draft1),
            config={"response_mime_type": "application/json"}
        )
        compressed_content = parse_json_safely(compress_resp.text)
        final_post = clean_text(compressed_content.get("post_text", ""))

        # 3. LENGTH CHECK
        ok, count = check_length_constraint(final_post)
        if not ok:
            safe_print(f"⚠️ Length Guard Failed: {count} sentences.")
            prompt += "\nERROR: Too long. Max 8 sentences."
            continue

        # 4. QUALITY GATE
        verdict = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{final_post}"
        ).text.strip()

        safe_print(f"🕵️ Senior Peer Verdict: {verdict}")

        if verdict == "PASS":
            return final_post

        prompt += "\nRewrite. Remove headers. Final sentence must focus on 'reasoning about pressure', not academic terms."

    safe_print("❌ Failed quality gate twice.")
    sys.exit(1)

def run_automation(dry_run=False):
    # 1. SETUP
    state = load_json(STATE_FILE, {"last_topics": [], "last_categories": []})
    client = genai.Client(api_key=GEMINI_KEY)

    # 2. SELECTION
    category, subtopic = select_topic(state)
    lens = random.choice(ANSWER_LENSES)
    posture = random.choice(OPENING_POSTURES)

    use_series_marker = (random.random() < 0.15)
    use_early_fail = (random.random() < 0.20)

    print("\n" + "="*50)
    print(f"📝 TOPIC:    {category.upper()}")
    print(f"🔍 PATTERN:  {subtopic}")
    print(f"🎲 VARIANT:  {'[Series Marker]' if use_series_marker else ''} {'[Early Fail]' if use_early_fail else '[Standard]'}")
    print("="*50 + "\n")

    # 3. GENERATE
    prompt = build_prompt(category, subtopic, lens, posture, use_series_marker, use_early_fail)
    post_text = generate_with_review(client, prompt)

    safe_print("✅ Content Generated:")
    safe_print(post_text)

    # 4. DRY RUN CHECK
    if dry_run:
        print("\n[DRY RUN MODE] Content not published.")
        history = load_json(HISTORY_FILE, [])
        history.append({
            "date": time.strftime("%Y-%m-%d"),
            "topic": f"{category}:{subtopic}",
            "status": "dry-run",
            "text": post_text
        })
        save_json(HISTORY_FILE, history[-50:])
        return

    # 5. PUBLISH
    urn = get_user_urn()
    if not urn:
        safe_print("❌ Invalid LinkedIn token.")
        return

    print("\n🚀 Publishing to LinkedIn...")
    if post_to_linkedin(urn, post_text):
        safe_print("✅ Published Successfully.")

        state["last_topics"].append(f"{category}:{subtopic}")
        state["last_topics"] = state["last_topics"][-15:]
        state["last_categories"].append(category)
        state["last_categories"] = state["last_categories"][-3:]
        save_json(STATE_FILE, state)

        history = load_json(HISTORY_FILE, [])
        history.append({
            "date": time.strftime("%Y-%m-%d"),
            "topic": f"{category}:{subtopic}",
            "status": "published",
            "text": post_text
        })
        save_json(HISTORY_FILE, history[-50:])
    else:
        safe_print("❌ Publish failed.")

# =============================
# ENTRYPOINT
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Generate content but do not publish")
    args = parser.parse_args()

    run_automation(dry_run=args.dry_run)