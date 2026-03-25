import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SUMMARY_PROMPT = """You are an expert meeting assistant. Analyze the following meeting transcript.

Your output MUST include these sections:

## Meeting Summary
A concise overview (150-200 words max).

## Key Discussion Points
- List each major topic with a brief explanation

## Action Items
- [ ] Action item - Owner - Deadline (if mentioned)

## Decisions Made
- List any decisions or agreements reached

## Open Questions
- List any unresolved questions

TRANSCRIPT:
{transcript}
"""


def generate_summary(transcript):
    if not transcript or len(transcript.strip()) < 50:
        return "Transcript too short to generate a meaningful summary."
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {"role": "system", "content": "You are a precise meeting summarizer."},
                {"role": "user", "content": SUMMARY_PROMPT.format(transcript=transcript)}
            ],
            max_tokens=2000,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Summary generation failed: {e}"
