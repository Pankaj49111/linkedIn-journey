# LinkedIn Story Bot

A small Python tool to draft and publish reflective technical posts to LinkedIn using a generative AI (Google Gemini via `google-genai`) and the LinkedIn REST API. The bot is opinionated about narrative structure, tone, and quality; it can produce a draft JSON (`current_draft.json`) and publish it to your LinkedIn account.

## What this repository contains

- `main_bot.py` - Primary CLI entrypoint. Two modes: `--mode draft` and `--mode publish`.
- `review_story.py` / `check_models.py` - helper scripts (project-specific utilities).
- `requirements.txt` - Python dependencies.
- `images/` - Optional folder for images that can be attached when publishing.

## Generated files (runtime)

The following files are created at runtime and are not necessarily committed to source control:

- `current_draft.json` - Draft output produced by `--mode draft` (contains `post_text`, `lesson_extracted`, and metadata).
- `story_state.json` - Tracks the act/episode counters and a short history of lessons/themes/techs.

Do not rely on these files being present in the repository; they are created and consumed by the bot at runtime.

## Prerequisites

- Python 3.8+ (3.10/3.11 recommended)
- A Google Gemini API key installed as `GEMINI_API_KEY` (used by the `google-genai` client).
- A LinkedIn access token with permissions to post on your behalf installed as `LINKEDIN_ACCESS_TOKEN`.

## Dependencies

This project depends on the Python packages listed in `requirements.txt`:

- requests
- google-genai

Install them with:

```powershell
python -m pip install -r requirements.txt
```

## Environment variables

Set your keys before running the bot. In PowerShell:

```powershell
$env:GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
$env:LINKEDIN_ACCESS_TOKEN = "YOUR_LINKEDIN_ACCESS_TOKEN"
```

On other shells (bash/zsh):

```bash
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
export LINKEDIN_ACCESS_TOKEN="YOUR_LINKEDIN_ACCESS_TOKEN"
```

## Usage

Generate a draft (writes `current_draft.json`):

```powershell
python main_bot.py --mode draft
```

Publish the saved draft to LinkedIn (reads `current_draft.json` and updates `story_state.json`):

```powershell
python main_bot.py --mode publish
```

If you place an image (png/jpg/jpeg/gif) into the `images/` folder before publishing, the first matching image will be uploaded and attached to the post.

## Files & State

- `current_draft.json` contains the AI-produced JSON with `post_text` and `lesson_extracted`. The publish step consumes this file and then deletes it after successful posting.
- `story_state.json` tracks the act/episode counters and a short history of previous lessons and used themes/techs.

## Troubleshooting

- `Invalid LinkedIn token.` or upload failures: ensure `LINKEDIN_ACCESS_TOKEN` is valid and has the right scopes.
- Gemini / `google-genai` errors: ensure `GEMINI_API_KEY` is set and the `google-genai` client is available/compatible with your Python version.
- If posts are truncated, the bot enforces a 2800-character limit and will trim the generated copy to keep required CTA/hashtags.

## Security

Do not commit API keys or tokens to source control. Use environment variables or a secrets manager. The files in the "Generated files (runtime)" section are produced locally and should generally be excluded from commits (add them to `.gitignore` if desired).

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.

## Contact

If you want improvements (extra features, more robust LinkedIn upload handling, or local testing utilities), open an issue or edit the repository directly.
