import os
import json
import shutil
from datetime import datetime

MEETINGS_DIR = "meetings"

def _ensure_dir():
      os.makedirs(MEETINGS_DIR, exist_ok=True)

def save_meeting(title, audio_path, transcript, summary):
      _ensure_dir()
      timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
      safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:50]
      folder_name = f"{timestamp}_{safe_title}"
      meeting_dir = os.path.join(MEETINGS_DIR, folder_name)
      os.makedirs(meeting_dir, exist_ok=True)
      if audio_path and os.path.exists(audio_path):
                ext = os.path.splitext(audio_path)[1]
                shutil.copy2(audio_path, os.path.join(meeting_dir, f"audio{ext}"))
            with open(os.path.join(meeting_dir, "transcript.txt"), "w", encoding="utf-8") as f:
                      f.write(transcript or "")
                  with open(os.path.join(meeting_dir, "summary.md"), "w", encoding="utf-8") as f:
                            f.write(summary or "")
                        metadata = {"title": title, "date": datetime.now().isoformat(), "timestamp": timestamp}
    with open(os.path.join(meeting_dir, "metadata.json"), "w") as f:
              json.dump(metadata, f, indent=2)
          return meeting_dir

def save_summary(meeting_path, summary):
      with open(os.path.join(meeting_path, "summary.md"), "w", encoding="utf-8") as f:
                f.write(summary)

def get_all_meetings():
      _ensure_dir()
    meetings = []
    for folder in sorted(os.listdir(MEETINGS_DIR), reverse=True):
              meeting_dir = os.path.join(MEETINGS_DIR, folder)
              meta_path = os.path.join(meeting_dir, "metadata.json")
              if os.path.isdir(meeting_dir) and os.path.exists(meta_path):
                            with open(meta_path) as f:
                                              meta = json.load(f)
                                          meta["path"] = meeting_dir
                            meetings.append(meta)
                    return meetings

def load_meeting(meeting_path):
      data = {}
    meta_path = os.path.join(meeting_path, "metadata.json")
    if os.path.exists(meta_path):
              with open(meta_path) as f:
                            data = json.load(f)
                    transcript_path = os.path.join(meeting_path, "transcript.txt")
    if os.path.exists(transcript_path):
              with open(transcript_path, encoding="utf-8") as f:
                            data["transcript"] = f.read()
                    summary_path = os.path.join(meeting_path, "summary.md")
    if os.path.exists(summary_path):
              with open(summary_path, encoding="utf-8") as f:
                            content = f.read().strip()
                            data["summary"] = content if content else None
                    return data
