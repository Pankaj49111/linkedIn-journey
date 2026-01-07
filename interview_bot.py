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

    # JVM Firewall
    for term in FORBIDDEN_TECH_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
            raise ValueError(f"Forbidden non-JVM term detected: {term}")

    text = re.sub(r'(?i)^(Hook|Lesson|Insight|Signal|Trap|Reality|Common Answer|Where it breaks|Where it holds|Context|Observation):', '', text, flags=re.MULTILINE)

    return text.strip()

def format_for_linkedin(text):
    """
    Forcefully inserts double newlines to prevent 'Wall of Text'.
    1. Standardizes existing newlines.
    2. If a paragraph is too long (>250 chars), it splits it.
    """
    # 1. Normalize line endings
    text = text.replace('\r\n', '\n').strip()

    # 2. Split by any existing paragraphs
    paragraphs = re.split(r'\n+', text)

    final_paragraphs = []
    for p in paragraphs:
        p = p.strip()
        if not p: continue

        if len(p) > 280:
            # Split by period, but keep the period
            sentences = re.split(r'(?<=[.!?]) +', p)
            # Group every 2 sentences into a new paragraph
            chunk = ""
            count = 0
            for s in sentences:
                chunk += s + " "
                count += 1
                if count >= 2:
                    final_paragraphs.append(chunk.strip())
                    chunk = ""
                    count = 0
            if chunk:
                final_paragraphs.append(chunk.strip())
        else:
            final_paragraphs.append(p)

    return "\n\n".join(final_paragraphs)

def check_length_constraint(text):
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if len(s.strip()) > 3]
    if len(sentences) > 9: return False, len(sentences)
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
    opening_instr = f"Start with: {posture}"
    if use_series_marker:
        marker = random.choice(SERIES_MARKERS)
        opening_instr = f"Start EXPLICITLY with this phrase: '{marker}'"

    if use_early_fail:
        structure_instr = "1. THE OBSERVATION\n2. THE EARLY CRACK (Fail immediately)\n3. THE CONSEQUENCE"
    else:
        structure_instr = "1. THE OBSERVATION\n2. THE CONTEXT\n3. THE GAP"

    return f"""
Role:
Senior Backend Engineer Peer.

CONTEXT:
- Topic: {category}
- Pattern: {subtopic}
- Lens: {lens}
- Opening: {opening_instr}

CONSTRAINTS:
1. JVM ONLY. No Node/Go/Rust.
2. NO EMOJIS.
3. Max 1 proper noun (e.g. "Hibernate").

TASK:
Write a short, narrative observation ({structure_instr}).

REVEAL SENTENCE:
Final sentence must follow: "This is usually where the discussion stops being about [Concept] and starts revealing how someone reasons about [System Risk]."

FORMATTING:
- USE DOUBLE NEWLINES between paragraphs.
- Keep paragraphs short (2-3 sentences max).
- JSON Output with escaped newlines (\\n).

OUTPUT JSON ONLY:
{{
  "post_text": "..."
}}
"""

def build_compress_prompt(original_text):
    return f"""
Role: Senior Editor.
Task: Fix the formatting and density of this text.

INPUT:
"{original_text}"

RULES:
1. **CRITICAL: MAINTAIN PARAGRAPH BREAKS.** Do NOT merge into one block.
2. Ensure there are exactly 3 distinct paragraphs separated by blank lines.
3. Remove "teaching" fluff.
4. Final sentence must be the "Reveal Sentence".
5. NO EMOJIS.

OUTPUT JSON ONLY:
{{
  "post_text": "..."
}}
"""

QUALITY_GATE_PROMPT = """
Role: Senior Engineer Peer.

FAIL if:
- Post is a single wall of text (no breaks).
- Post uses emojis.
- Tone is academic.
- Length > 9 sentences.

PASS if:
- Structure is 3 clearly separated paragraphs.
- Tone is observational.

Respond exactly: PASS or FAIL
"""

def generate_with_review(client, prompt):
    for attempt in range(2):
        safe_print(f"🔄 Generation Attempt {attempt + 1}")

        # 1. GENERATE
        response = client.models.generate_content(
            model="gemini-flash-latest", contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        content = parse_json_safely(response.text)
        draft1 = clean_text(content.get("post_text", ""))

        safe_print("🔨 Running Auto-Compressor...")
        compress_resp = client.models.generate_content(
            model="gemini-flash-latest", contents=build_compress_prompt(draft1),
            config={"response_mime_type": "application/json"}
        )
        compressed_content = parse_json_safely(compress_resp.text)
        post_text = clean_text(compressed_content.get("post_text", ""))

        final_post = format_for_linkedin(post_text)

        ok, count = check_length_constraint(final_post)
        if not ok:
            prompt += "\nERROR: Too long. Cut to max 8 sentences."
            continue

        verdict = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{QUALITY_GATE_PROMPT}\n\nPOST:\n{final_post}"
        ).text.strip()

        safe_print(f"🕵️ Verdict: {verdict}")

        if verdict == "PASS":
            return final_post

        prompt += "\nRewrite. Force double newlines between paragraphs."

    safe_print("❌ Failed quality gate.")
    sys.exit(1)

def run_automation(dry_run=False):
    state = load_json(STATE_FILE, {"last_topics": [], "last_categories": []})
    client = genai.Client(api_key=GEMINI_KEY)

    category, subtopic = select_topic(state)
    lens = random.choice(ANSWER_LENSES)
    posture = random.choice(OPENING_POSTURES)

    use_series_marker = (random.random() < 0.15)
    use_early_fail = (random.random() < 0.20)

    print("\n" + "="*50)
    print(f"📝 TOPIC:    {category.upper()}")
    print(f"🔍 PATTERN:  {subtopic}")
    print("="*50 + "\n")

    prompt = build_prompt(category, subtopic, lens, posture, use_series_marker, use_early_fail)
    post_text = generate_with_review(client, prompt)

    safe_print("✅ Content Generated:")
    safe_print(post_text)

    if dry_run:
        print("\n[DRY RUN MODE]")
        history = load_json(HISTORY_FILE, [])
        history.append({"date": time.strftime("%Y-%m-%d"), "topic": f"{category}:{subtopic}", "status": "dry-run", "text": post_text})
        save_json(HISTORY_FILE, history[-50:])
        return

    urn = get_user_urn()
    if not urn:
        safe_print("❌ Invalid LinkedIn token.")
        return

    print("\n🚀 Publishing...")
    if post_to_linkedin(urn, post_text):
        safe_print("✅ Published.")
        state["last_topics"].append(f"{category}:{subtopic}")
        state["last_topics"] = state["last_topics"][-15:]
        state["last_categories"].append(category)
        state["last_categories"] = state["last_categories"][-3:]
        save_json(STATE_FILE, state)

        history = load_json(HISTORY_FILE, [])
        history.append({"date": time.strftime("%Y-%m-%d"), "topic": f"{category}:{subtopic}", "status": "published", "text": post_text})
        save_json(HISTORY_FILE, history[-50:])
    else:
        safe_print("❌ Publish failed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_automation(dry_run=args.dry_run)