*** Begin Patch
*** Update File: src/main.py
@@
 from config import SETTINGS
 from content import choose_topic, generate_script
 from media import render, validate
 from youtube import upload
 from meta import publish as publish_meta
 from guards import enforce, load_history, save_history
+from .utils import sanitize_hashtags, unique_text_suffix
@@
-    video_history_path = SETTINGS.data_dir / "video_history.json"
-    video_history = load_history(video_history_path)
-    video_history.append(result)
-    video_history_path.write_text(json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
+    video_history_path = SETTINGS.data_dir / "video_history.json"
+    video_history = load_history(video_history_path)
+
+    # History-aware duplication avoidance:
+    # Compare newly generated title/description/hashtags to last N entries and modify if too similar.
+    def _is_similar(a: str, b: str) -> bool:
+        if not a or not b:
+            return False
+        # simple exact or substring check - keep conservative and fast
+        a_norm = a.strip().lower()
+        b_norm = b.strip().lower()
+        if a_norm == b_norm:
+            return True
+        if a_norm in b_norm or b_norm in a_norm:
+            return True
+        return False
+
+    recent = list(reversed(video_history[-SETTINGS.duplicate_check_last:])) if video_history else []
+    title = result.get("title", "")
+    description = result.get("description", "") if isinstance(result.get("description"), str) else ""
+    hashtags = result.get("hashtags", []) if isinstance(result.get("hashtags"), list) else []
+
+    collision = False
+    for prev in recent:
+        if not isinstance(prev, dict):
+            continue
+        if _is_similar(title, prev.get("title", "")):
+            collision = True
+            break
+        if _is_similar(description, prev.get("description", "")):
+            collision = True
+            break
+        # hashtags comparison: treat as set of normalized tags
+        prev_tags = {t.lstrip("#").strip().lower() for t in prev.get("hashtags", [])}
+        new_tags = {t.lstrip("#").strip().lower() for t in hashtags}
+        if prev_tags == new_tags and new_tags:
+            collision = True
+            break
+
+    if collision:
+        # Try non-destructive adjustments first: add a short unique suffix and re-sanitize hashtags
+        suffix = unique_text_suffix(title)
+        if suffix:
+            result["title"] = (title + suffix)[:70]
+            result["description"] = (description + suffix)[:3000]
+            result["hashtags"] = sanitize_hashtags(hashtags, max_hashtags=SETTINGS.max_hashtags)
+        else:
+            # If suffix wasn't produced, force regenerate by tweaking the topic slightly
+            result["title"] = (title + f" #{int(time.time()) % 1000}")[:70]
+            result["description"] = (description + f"\n\nVariant {int(time.time()) % 1000}")[:3000]
+            result["hashtags"] = sanitize_hashtags(hashtags, max_hashtags=SETTINGS.max_hashtags)
+
+    video_history.append(result)
+    video_history_path.write_text(json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
*** End Patch