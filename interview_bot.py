import os
import json
import argparse
import requests
from google import genai
from google.genai import types
import sys
import random
import re
import time
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

HISTORY_FILE = "interview_history.json"
STATE_FILE = "interview_state.json"
FAILED_DRAFTS_FILE = "interview_failed_drafts.json"

LINKEDIN_VERSIONS_FALLBACK = [
    "202511", "202510", "202509", "202508", "202507", "202506",
    "202505", "202504", "202503", "202502", "202501",
    "202412", "202411", "202410", "202409", "202408", "202407", "202406", "202401"
]

FIXED_HASHTAGS = "\n\n#backend #engineering #interviews #java #systemsdesign #jvm"

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
    "QA_STYLE_DETECTED": """
    EDITOR REQUEST: You are writing like a Q&A exam. Stop.
    Remove all "Question:" or "Answer:" labels.
    Describe the *pattern* of the answer ("Most candidates mention X..."), not the quote itself.
    """,
    "TOO_PREACHY": """
    EDITOR REQUEST: You sound like a tutorial ("You should always...").
    Switch to EVALUATOR tone ("This tells me...", "This signals...").
    Don't teach the concept; judge the reasoning.
    """,
    "MISSING_TENSION": """
    EDITOR REQUEST: The post is too flat. It lacks narrative tension.
    You must describe what you were WAITING to hear, but didn't.
    "I waited for them to mention X, but they stopped at Y."
    """,
    "MISSING_MIRROR": """
    EDITOR REQUEST: You missed the 'Mirror Line'.
    Add a sentence that implicates the reader/candidate, like:
    "It's an answer I've heard myself give." or "Most strong resumes stop right here."
    """,
    "EXPLICIT_TEACHING": """
    EDITOR REQUEST: You are explaining the technology. Stop.
    Assume the reader knows what the tech is.
    Focus entirely on what the candidate's answer REVEALS about their seniority.
    """,
    "PRODUCT_NAMING_DETECTED": """
    EDITOR REQUEST: Do NOT name specific products (WhatsApp, Uber, Netflix).
    Describe the BEHAVIOR instead:
    - Instead of "WhatsApp", say "Long-lived connection systems".
    - Instead of "Twitter", say "High fan-out models".
    """,
    "DESIGN_TUTORIAL_TONE": """
    EDITOR REQUEST: You are explaining 'How to design X'. Stop.
    Focus on 'Where the design breaks'.
    Identify the specific pressure point (e.g., reconnect storms) where the candidate's model collapses.
    """,
    "FORBIDDEN_TERM": """
    CRITICAL FAILURE: You used a forbidden term (Node, Go, Python, etc.).
    This account is strictly JVM/Backend engineering.
    Rewrite entirely using JVM terminology (Thread Pools, GC, Heap) or generic systems terms.
    """
}

# =============================
# 🗄️ IMPLICIT AXIS DATABASE
# =============================
INTERVIEW_TOPICS = {
    "relational_db": [
        {
            "topic": "Isolation levels breaking financial correctness",
            "axis": "State Ownership Axis",
            "signal": "Do they understand where truth lives vs where it is read?",
            "anchor": "The numbers were internally consistent. They were still wrong."
        },
        {
            "topic": "Connection pools masking slow queries",
            "axis": "Resource Contention Axis",
            "signal": "Do they recognize indirect bottlenecks beyond CPU?",
            "anchor": "The database wasn't slow. Requests were just waiting."
        },
        {
            "topic": "Indexes accelerating reads while killing writes",
            "axis": "Recovery Cost Axis",
            "signal": "Trade-off awareness and rollback thinking.",
            "anchor": "The improvement worked. Rolling it back didn't."
        },
        {
            "topic": "Long transactions holding invisible locks",
            "axis": "Resource Contention Axis",
            "signal": "Debugging without alerts; lock visibility intuition.",
            "anchor": "Nothing was failing. Everything was blocked."
        }
    ],
    "nosql_misuse": [
        {
            "topic": "Eventual consistency leaking into user workflows",
            "axis": "State Ownership Axis",
            "signal": "Modeling inconsistency impact on users.",
            "anchor": "The system behaved correctly. Users didn't experience it that way."
        },
        {
            "topic": "Hot partitions created by innocent keys",
            "axis": "Backpressure Axis",
            "signal": "Load distribution intuition and non-linear scaling.",
            "anchor": "Most requests were fast. A few were unbearably slow."
        },
        {
            "topic": "Compaction pauses mistaken for traffic spikes",
            "axis": "Visibility vs Reality Axis",
            "signal": "Metric skepticism and false correlation detection.",
            "anchor": "Traffic never increased. Latency did."
        }
    ],
    "derived_stores": [
        {
            "topic": "Dual writes without atomicity",
            "axis": "State Ownership Axis",
            "signal": "Repair complexity awareness.",
            "anchor": "We couldn't tell which side was wrong anymore."
        },
        {
            "topic": "Search indexes lagging behind truth",
            "axis": "Visibility vs Reality Axis",
            "signal": "Asynchronous correctness and user trust impact.",
            "anchor": "The data was correct. The answers weren't."
        },
        {
            "topic": "Backfills causing production brownouts",
            "axis": "Backpressure Axis",
            "signal": "Operational empathy and safe repair strategies.",
            "anchor": "Fixing old data broke new traffic."
        }
    ],
    "kafka": [
        {
            "topic": "Ordering guarantees vs Consumer Group rebalances",
            "axis": "Ordering Guarantees Axis",
            "signal": "Replay awareness and non-linear time reasoning.",
            "anchor": "The event arrived again. This time it mattered."
        },
        {
            "topic": "The myth of 'Exactly Once' in distributed systems",
            "axis": "Human Assumption Axis",
            "signal": "Overconfidence detection; pragmatism vs theory.",
            "anchor": "The guarantee existed. The assumptions didn't."
        },
        {
            "topic": "Consumer lag: Latency vs Throughput trade-off",
            "axis": "Backpressure Axis",
            "signal": "Queueing intuition and trade-off reasoning.",
            "anchor": "Nothing timed out. Everything was late."
        }
    ],
    "redis": [
        {
            "topic": "Using Redis as a primary database (The Persistence Trap)",
            "axis": "State Ownership Axis",
            "signal": "Durability thinking and long-term risk awareness.",
            "anchor": "It was fast until it wasn't there anymore."
        },
        {
            "topic": "Distributed locks: The Clock Skew problem",
            "axis": "Ordering Guarantees Axis",
            "signal": "Time skepticism and failure mode imagination.",
            "anchor": "The lock expired. The work didn't."
        },
        {
            "topic": "Eviction policies silently killing business logic",
            "axis": "Failure Detection Axis",
            "signal": "Silent failure awareness and cache skepticism.",
            "anchor": "The system forgot something important."
        }
    ],
    "jvm_mechanics": [
        {
            "topic": "Thread Pool Exhaustion vs CPU saturation",
            "axis": "Resource Contention Axis",
            "signal": "Queue vs compute distinction.",
            "anchor": "CPU was idle. Requests weren't moving."
        },
        {
            "topic": "Stop-the-world GC pauses vs Network Latency",
            "axis": "Visibility vs Reality Axis",
            "signal": "Root cause patience and JVM internals intuition.",
            "anchor": "Everything froze. The network took the blame."
        },
        {
            "topic": "JVM Warm-up: Why autoscaling is slow",
            "axis": "Initialization & Warm-up Axis",
            "signal": "Lifecycle thinking; cold vs steady-state reasoning.",
            "anchor": "Scaling worked. Starting didn't."
        }
    ]
}

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
    text = text.replace("```json", "").replace("```", "")

    # 🚨 HARD BLOCK: Raise error if forbidden term is found
    for term in FORBIDDEN_TECH_TERMS:
        if re.search(rf"\b{re.escape(term.strip())}\b", text, re.IGNORECASE):
            # Exception triggers the mutation loop to retry
            raise ValueError(f"Forbidden term detected: '{term.strip()}'")

    text = re.sub(r'(?i)^(Hook|Lesson|Insight|Signal|Trap|Reality|Common Answer|Where it breaks|Where it holds|Context|Observation):', '', text, flags=re.MULTILINE)
    return text.strip()

def log_failure(post, axis, note, topic, subtopic):
    if not os.path.exists(FAILED_DRAFTS_FILE):
        failures = []
    else:
        try:
            with open(FAILED_DRAFTS_FILE, "r", encoding="utf-8") as f: failures = json.load(f)
        except: failures = []

    failures.append({
        "date": datetime.now().isoformat(),
        "topic_context": f"{topic} -> {subtopic}",
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

# 🔧 PRE-FLIGHT CHECK
def structural_precheck(post):
    if re.search(r"\b(Question|Answer|Candidate):\s", post, re.IGNORECASE):
        return False, "QA_STYLE_DETECTED"

    if re.search(r"\b(You should|You must|Make sure|Ensure that)\b", post, re.IGNORECASE):
        return False, "TOO_PREACHY"

    if re.search(r"\b(WhatsApp|Uber|Netflix|Twitter|Facebook|Instagram)\b", post, re.IGNORECASE):
        return False, "PRODUCT_NAMING_DETECTED"
    return True, None

# 🔧 FORMATTING ENGINE (Fixed for Half-Post Bug)
def format_for_linkedin(text):
    text = text.replace('\r\n', '\n').strip()

    # 1. VISUAL HOOK: Isolate the first sentence if it's reasonably short
    match = re.match(r'(.*?[.!?])(\s+)(.*)', text, re.DOTALL)
    if match:
        hook = match.group(1).strip()
        rest = match.group(3).strip()
        if len(hook) < 150:
            text = f"{hook}\n\n{rest}"

    # 2. Simple Paragraph Spacing
    # Aggressive splitting was causing data loss with complex punctuation.
    # This safer logic just ensures clean separation.
    paragraphs = re.split(r'\n+', text)
    formatted_paragraphs = [p.strip() for p in paragraphs if p.strip()]

    return "\n\n".join(formatted_paragraphs)

# =============================
# LOGIC
# =============================
def select_topic(state):
    last_topics = state.get("last_topics", [])
    last_axes = state.get("last_axes", [])

    categories = list(INTERVIEW_TOPICS.keys())
    category = random.choice(categories)

    subtopic_objects = INTERVIEW_TOPICS[category]
    valid_candidates = []
    for obj in subtopic_objects:
        is_fresh_topic = obj["topic"] not in last_topics
        is_fresh_axis = obj["axis"] not in last_axes[-2:]
        if is_fresh_topic and is_fresh_axis:
            valid_candidates.append(obj)

    if not valid_candidates:
        valid_candidates = subtopic_objects

    selected_obj = random.choice(valid_candidates)
    return category, selected_obj

def get_user_urn():
    try:
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200: return None
        return resp.json().get("sub")
    except Exception: return None

# 🛠️ SELF-HEALING POST FUNCTION
def post_to_linkedin(urn, text):
    text = format_for_linkedin(text)
    url = "https://api.linkedin.com/rest/posts"
    full_text = text.strip() + FIXED_HASHTAGS

    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": full_text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

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

            # If 426 (Version Not Supported), loop to next version
            if resp.status_code == 426:
                safe_print(f"⚠️ Version {version} not active. Retrying...")
                continue

            safe_print(f"❌ LinkedIn Error [{resp.status_code}]: {resp.text}")
            return False

        except Exception as e:
            safe_print(f"❌ Network Error: {e}")
            return False

    safe_print("❌ All LinkedIn versions failed.")
    return False

# =============================
# PROMPTS & JUDGE
# =============================
QUALITY_GATE_PROMPT = """
Role: Principal Engineer / Hiring Bar Raiser.

Review the post below.

FAIL if:
1. It feels like "Content Creation" (Tips, Tricks, Tutorials).
2. It uses Q&A labels ("Question:", "Answer:").
3. It gives advice ("You should...").
4. It names specific products (WhatsApp, Uber, etc.).
5. It lacks NARRATIVE TENSION (doesn't describe what was *missing* or *unsaid*).

PASS_9_PLUS only if:
- It describes SYSTEM PRESSURE (long-lived connections, fan-out, churn).
- It creates a moment of silence/judgment where a follow-up question was WITHHELD.

OUTPUT JSON ONLY:
{
  "verdict": "PASS_9_PLUS" OR "FAIL",
  "failure_axis": "QA_STYLE_DETECTED" | "TOO_PREACHY" | "MISSING_TENSION" | "MISSING_MIRROR" | "PRODUCT_NAMING_DETECTED" | "DESIGN_TUTORIAL_TONE",
  "editor_note": "Reason"
}
"""

def build_prompt(category, topic_obj, lens, posture, use_series_marker, use_early_fail):
    opening_instr = f"Start with: {posture}"
    if use_series_marker:
        marker = random.choice(SERIES_MARKERS)
        opening_instr = f"Start EXPLICITLY with this phrase: '{marker}'"

    subtopic = topic_obj["topic"]
    axis = topic_obj["axis"]
    signal = topic_obj["signal"]
    anchor = topic_obj["anchor"]

    return f"""
Role:
Principal Backend Evaluator.

CONTEXT:
- Topic: {subtopic}
- Hidden Axis: {axis}
- Interview Signal: {signal}
- Lens: {lens}
- Opening: {opening_instr}

CONSTRAINTS:
1. JVM ONLY. No Node/Go/Rust.
2. NO EMOJIS.
3. NO "You should" / "Always" / "Never". (Anti-Advice Rule)
4. NO "Question:" or "Answer:" labels. (Anti-Q&A Rule)
5. DO NOT name products (WhatsApp, Uber). Describe behavior.
6. MANDATORY: First sentence must be short (under 15 words) and arresting.

PSYCHOLOGICAL RULES (MANDATORY):
1. THE UNASKED QUESTION: Describe waiting for the candidate to mention something critical—and they don't.
2. DELIBERATE SILENCE: Include a moment where you *choose not to ask* the follow-up because the signal is clear.
3. THE MIRROR LINE: Include a sentence that implicates the reader (e.g., "Most strong resumes stop here" or "It sounds correct until you've lived it").

TASK:
Write a first-person observation of a candidate's answer pattern.
1. Describe the pattern indirectly.
2. Describe your visceral internal reaction.
3. Use the 'Hidden Axis' to focus on pressure points.

NARRATIVE ANCHOR (Must appear in spirit):
"{anchor}"

[[EDITOR_FEEDBACK_SLOT]]

REVEAL SENTENCE:
Final sentence must follow: "This is usually where the discussion stops being about [Concept] and starts revealing how someone reasons about [System Risk]."

FORMATTING:
- USE DOUBLE NEWLINES between paragraphs.
- Keep paragraphs short (2-3 sentences max).

OUTPUT JSON ONLY:
{{
  "post_text": "..."
}}
"""

# =============================
# MUTATION LOOP
# =============================
def generate_with_review(client, base_prompt, context_tuple):
    category, subtopic = context_tuple
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

            # This will RAISE ValueError if forbidden term found
            post = clean_text(content.get("post_text", ""))

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

            axis = verdict_data.get("failure_axis", "TOO_PREACHY")
            if axis == previous_axis:
                safe_print("⚠️ Same failure axis repeated. Stopping mutation.")
                return content

            previous_axis = axis
            mutation = PROMPT_MUTATIONS.get(axis, PROMPT_MUTATIONS["TOO_PREACHY"])

            safe_print(f"💉 Injecting Mutation: {axis}")
            feedback_text = f"\n--- EDITOR FEEDBACK ---\n{mutation}\nTASK: Rewrite applying this fix."

        except ValueError as ve:
            # Handle forbidden terms by treating them as a "mutation" failure
            safe_print(f"🚫 {ve}")
            if attempt < MAX_ATTEMPTS - 1:
                feedback_text = f"\n--- CRITICAL FEEDBACK ---\n{PROMPT_MUTATIONS['FORBIDDEN_TERM']}"
                continue
            else:
                # If last attempt failed due to forbidden term, we cannot publish it
                safe_print("❌ Failed due to Forbidden Term on last attempt.")
                sys.exit(1)
        except Exception as e:
            safe_print(f"⚠️ Unexpected Error: {e}")
            continue

    safe_print("⚠️ Quality Gate failed after max attempts. Soft landing initiated.")

    if last_content:
        log_failure(last_content["post_text"], previous_axis, verdict_data.get("editor_note", "Max attempts"), category, subtopic)
        return last_content

    safe_print("❌ Critical Failure: No content generated.")
    sys.exit(1)

# =============================
# MAIN AUTOMATION
# =============================
def run_automation(dry_run=False):
    # BACKWARD COMPATIBILITY: Force 'last_axes' if missing
    state = load_json(STATE_FILE, {"last_topics": [], "last_categories": [], "last_axes": []})
    state.setdefault("last_axes", [])
    state.setdefault("last_topics", [])
    state.setdefault("last_categories", [])

    client = genai.Client(api_key=GEMINI_KEY)

    category, topic_obj = select_topic(state)
    subtopic = topic_obj["topic"]
    axis = topic_obj["axis"]

    lens = random.choice(ANSWER_LENSES)
    posture = random.choice(OPENING_POSTURES)
    use_series_marker = (random.random() < 0.15)
    use_early_fail = (random.random() < 0.20)

    print("\n" + "="*50)
    print(f"📝 TOPIC:    {category.upper()}")
    print(f"🔍 PATTERN:  {subtopic}")
    print(f"⚖️ AXIS:     {axis}")
    print("="*50 + "\n")

    base_prompt = build_prompt(category, topic_obj, lens, posture, use_series_marker, use_early_fail)

    final_content = generate_with_review(client, base_prompt, (category, subtopic))
    post_text = final_content["post_text"]
    post_text = format_for_linkedin(post_text)

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

        state["last_topics"].append(subtopic)
        state["last_topics"] = state["last_topics"][-15:]
        state["last_categories"].append(category)
        state["last_categories"] = state["last_categories"][-3:]
        state["last_axes"].append(axis)
        state["last_axes"] = state["last_axes"][-2:]
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