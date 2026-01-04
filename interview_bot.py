import os
import json
import argparse
import requests
from google import genai
import sys
import random
import re
import time
import urllib.parse

# =============================
# FORCE UTF-8 OUTPUT
# =============================
sys.stdout.reconfigure(encoding="utf-8")

# =============================
# CONFIGURATION
# =============================
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

HISTORY_FILE = "interview_history.json"
STATE_FILE = "interview_state.json"

LINKEDIN_API_VERSION = "202411"

FIXED_HASHTAGS = "\n\n#backend #engineering #interviews #java #systemsdesign #jvm"

INTERVIEW_TOPICS = {
    # 1. PRIMARY STORAGE (The Truth)
    "relational_db": [
        "Isolation levels breaking financial correctness",
        "Connection pools masking slow queries",
        "Indexes accelerating reads while killing writes",
        "Long transactions holding invisible locks",
        "Schema evolution locking tables under load"
    ],
    # 2. SUPPORTING SYSTEMS (The Scale)
    "nosql_misuse": [
        "Eventual consistency leaking into user workflows",
        "Hot partitions created by innocent keys",
        "Compaction pauses mistaken for traffic spikes",
        "Secondary indexes lying under load"
    ],
    # 3. DERIVED DATA (The View)
    "derived_stores": [
        "Dual writes without atomicity",
        "Search indexes lagging behind truth",
        "Backfills causing production brownouts",
        "Read models drifting silently from source"
    ],
    # 4. ASYNC & BROKERS
    "kafka": [
        "Ordering guarantees vs Consumer Group rebalances",
        "The myth of 'Exactly Once' in distributed systems",
        "Consumer lag: Latency vs Throughput trade-off",
        "Retries destroying strict event ordering"
    ],
    # 5. CACHING & STATE
    "redis": [
        "Using Redis as a primary database (The Persistence Trap)",
        "Distributed locks: The Clock Skew problem",
        "Eviction policies silently killing business logic",
        "Large keys blocking the single-threaded loop"
    ],
    # 6. JVM RUNTIME & INFRA
    "jvm_mechanics": [
        "Thread Pool Exhaustion vs CPU saturation",
        "Stop-the-world GC pauses vs Network Latency",
        "JVM Warm-up: Why autoscaling is slow",
        "The cost of Java Object Serialization in high-throughput systems"
    ]
}

# =============================
# JVM FIREWALL (Strict Language Guard)
# =============================
FORBIDDEN_TECH_TERMS = [
    "node", "nodejs", "node.js",
    "event loop", "callback hell", # Specific to Node/JS patterns
    "goroutine", "go routine", "golang", "channels",
    "python", "gil", "flask", "django",
    "rust", "ownership model", "borrow checker",
    ".net", "c#", "async await", "task"
]

# =============================
# TONE & POSTURE
# =============================
ANSWER_LENSES = [
    "Failure Mode (How it breaks)",
    "Operational Cost (How it wakes us up)",
    "Scaling Edge Case (What happens at 10x)",
    "Human Assumption (What we forgot to ask)",
    "Latency vs Throughput Trade-off",
    "Consistency vs Availability Trade-off"
]

OPENING_POSTURES = [
    "A neutral observation ('It is common to see...')",
    "A mild contradiction ('We often assume X, but...')",
    "A quiet doubt ('I am skeptical when I hear...')",
    "A direct pattern match ('The pattern usually starts with...')"
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
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)

def clean_text(text):
    if not text:
        return ""

    text = text.replace("*", "")

    # 1. JVM FIREWALL CHECK
    for term in FORBIDDEN_TECH_TERMS:
        # Regex to find whole words, case-insensitive
        if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
            raise ValueError(f"Forbidden non-JVM term detected: {term}")

    # 2. Structure Cleanup
    text = re.sub(r'(?i)^(Hook|Lesson|Insight|Signal|Trap|Reality|Common Answer|Where it breaks|Where it holds):', '', text, flags=re.MULTILINE)

    return text.strip()

def select_topic(state):
    last_topics = state.get("last_topics", [])
    last_categories = state.get("last_categories", [])
    categories = list(INTERVIEW_TOPICS.keys())

    # Bias against recently used categories
    available_categories = [c for c in categories if c not in last_categories]
    if not available_categories:
        available_categories = categories

    category = random.choice(available_categories)

    subtopics = INTERVIEW_TOPICS[category]
    available_subtopics = [t for t in subtopics if t not in last_topics]

    if not available_subtopics:
        available_subtopics = subtopics

    subtopic = random.choice(available_subtopics)

    return category, subtopic

def select_lens_and_posture():
    return random.choice(ANSWER_LENSES), random.choice(OPENING_POSTURES)

def check_length_constraint(text):
    """Hard guard against rambling."""
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if len(s.strip()) > 3]

    if len(sentences) > 8:
        return False, len(sentences)
    return True, len(sentences)

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

# =============================
# QUALITY GATE
# =============================
QUALITY_GATE_PROMPT = """
Role: Experienced Senior Engineer Peer (Java/JVM Context).

FAIL if:
- Post references non-JVM tech (Node, Go, Python, Rust).
- Post explains concepts like a textbook.
- Post sounds like a judge/interviewer.
- Post gives direct advice ("You should").
- Post is condescending.
- Post uses emojis.

PASS if:
- Tone is observational ("I've seen this break when...").
- Context is strictly Backend Engineering (JVM implied).
- Structure flows: Concept -> Context -> The Edge Case.

Respond with exactly:
PASS or FAIL
"""

# =============================
# PROMPT BUILDER
# =============================
def build_prompt(category, subtopic, lens, posture):
    return f"""
Role:
You are a Senior Backend Engineer reflecting on patterns you've seen in interviews and production reviews.
You are NOT the interviewer. You are the peer who knows why the "textbook answer" causes pager alerts.

CONTEXT:
- Topic: {category}
- Specific Pattern: {subtopic}
- ANALYSIS LENS: {lens}
- OPENING POSTURE: {posture}

LANGUAGE CONSTRAINT (STRICT):
- All examples, failures, and behaviors must be explainable within a JVM-based backend system.
- Do NOT reference other languages, runtimes, or frameworks (Node.js, Go, Python, Rust, .NET, etc.).
- If a concept is generic, describe it using Java/JVM execution semantics (threads, GC, connection pools, blocking I/O).

TASK:
Write a short, grounded observation about a technical nuance.

STRUCTURE (3 Paragraphs max):
1. THE COMMON ANSWER: The standard, confident response most engineers give.
2. WHERE IT HOLDS: Briefly acknowledge where this answer is actually correct (Senior engineers know trade-offs).
3. WHERE IT BREAKS: The specific production scenario where this assumption fails (The "Senior" insight).

TONE RULES:
- Observational, not judgmental.
- Phrases like "It works until...", "The gap usually appears when...", "I've noticed...".
- NO "Candidates fail". NO "You should". NO "Always".
- NO Emojis.
- Max 7 sentences total.

OUTPUT JSON ONLY:
{{
  "post_text": "..."
}}
"""

# =============================
# GENERATE + REVIEW
# =============================
def generate_with_review(client, prompt):
    for attempt in range(2):
        safe_print(f"🔄 Generation Attempt {attempt + 1}")

        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )

        content = json.loads(response.text)

        # 1. CLEAN & JVM FIREWALL
        try:
            post = clean_text(content["post_text"])
        except ValueError as e:
            safe_print(f"⚠️ JVM Firewall Triggered: {e}. Rewriting.")
            prompt += f"\nERROR: You used a forbidden term ({e}). Stick strictly to Java/JVM backend concepts."
            continue

        # 2. HARD GUARD: Sentence Length
        is_short_enough, count = check_length_constraint(post)
        if not is_short_enough:
            safe_print(f"⚠️ Failed Length Guard: {count} sentences. Rewriting.")
            prompt += "\nERROR: The text was too long. Strict limit: 7 sentences maximum. Cut the explanation."
            continue

        # 3. SEMANTIC GUARD: Quality Gate
        verdict = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{post}"
        ).text.strip()

        safe_print(f"🕵️ Senior Peer Verdict: {verdict}")

        if verdict == "PASS":
            return post

        prompt += "\nRewrite. Less 'interviewer', more 'production veteran'. Strict JVM context."

    safe_print("❌ Failed quality/length gate twice.")
    sys.exit(1)

# =============================
# MAIN AUTOMATION LOOP
# =============================
def run_automation(dry_run=False):
    # 1. SETUP
    state = load_json(STATE_FILE, {"last_topics": [], "last_categories": []})
    client = genai.Client(api_key=GEMINI_KEY)

    # 2. SELECT TOPIC, LENS, & POSTURE
    category, subtopic = select_topic(state)
    lens, posture = select_lens_and_posture()

    print("\n" + "="*40)
    safe_print(f"📝 TOPIC:   {category.upper()}")
    safe_print(f"🔍 PATTERN: {subtopic}")
    safe_print(f"👓 LENS:    {lens}")
    safe_print(f"🗣️ POSTURE: {posture}")
    print("="*40 + "\n")

    # 3. GENERATE
    prompt = build_prompt(category, subtopic, lens, posture)
    post_text = generate_with_review(client, prompt)

    safe_print("✅ Content Generated:")
    safe_print(post_text)

    # 4. DRY RUN CHECK
    if dry_run:
        print("\n[DRY RUN MODE] Content not published.")
        history = load_json(HISTORY_FILE, [])
        history.append({"date": time.strftime("%Y-%m-%d"), "topic": f"{category}:{subtopic}", "status": "dry-run", "text": post_text})
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

        # Update State
        state["last_topics"].append(f"{category}:{subtopic}")
        state["last_topics"] = state["last_topics"][-15:]

        state["last_categories"].append(category)
        state["last_categories"] = state["last_categories"][-3:]

        save_json(STATE_FILE, state)

        # Log History
        history = load_json(HISTORY_FILE, [])
        history.append({"date": time.strftime("%Y-%m-%d"), "topic": f"{category}:{subtopic}", "status": "published", "text": post_text})
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