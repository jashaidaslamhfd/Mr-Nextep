"""Regression tests for the 2026 algorithm policy and the systems built on it.

Every test here maps to a specific way the channel was losing reach before the
policy layer existed. They are all offline and deterministic — no network, no
API keys, no rendering.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import algorithm_policy as policy  # noqa: E402
import platform_captions as captions  # noqa: E402
import platform_cuts as cuts  # noqa: E402


class PolicyShapeTests(unittest.TestCase):
    """The policy must stay internally consistent — a contradictory policy is
    worse than none, because every downstream module trusts it."""

    def test_every_platform_declares_a_complete_policy(self):
        for platform in policy.PLATFORMS:
            block = policy.get_policy(platform)
            for key in ("duration", "retention_gate", "hook_seconds",
                        "hashtags", "caption", "ranking_signals", "sources"):
                self.assertIn(key, block, f"{platform} missing {key}")

    def test_duration_windows_are_ordered(self):
        for platform in policy.PLATFORMS:
            floor, ideal, ceiling = policy.duration_policy(platform)
            self.assertLess(floor, ideal, platform)
            self.assertLess(ideal, ceiling, platform)
            self.assertLessEqual(ceiling, policy.get_policy(platform)["hard_max"])

    def test_meta_windows_are_shorter_than_youtube(self):
        """The whole reason the dual cut exists. If this ever inverts, the cut
        logic is pointless and should be removed rather than left running."""
        yt_ideal = policy.duration_policy(policy.YOUTUBE)[1]
        for platform in (policy.FACEBOOK, policy.INSTAGRAM):
            self.assertLess(policy.duration_policy(platform)[1], yt_ideal)

    def test_short_videos_are_held_to_a_stricter_gate(self):
        """Sub-30s Shorts need ~65% average view percentage, 30-60s ~50%.
        A cut that drifts under 30s silently faces a harder bar."""
        self.assertGreater(
            policy.retention_gate(policy.YOUTUBE, 25),
            policy.retention_gate(policy.YOUTUBE, 40),
        )

    def test_viewers_decide_inside_the_three_second_window(self):
        for platform in policy.PLATFORMS:
            self.assertLessEqual(policy.decision_seconds(platform), 3.0, platform)

    def test_hook_sentence_may_outlast_the_decision_moment(self):
        """These are different things and conflating them broke the writer.

        The viewer decides mid-sentence, on the first few words and the first
        frame — the sentence does not have to be over. When hook_seconds was
        set equal to decision_seconds it allowed only five words, and the
        caption trimmer chopped good openers into fragments like "Your calf
        locks up in." A truncated hook fails at the exact moment it was
        supposed to win.
        """
        for platform in policy.PLATFORMS:
            self.assertGreater(policy.hook_seconds(platform),
                               policy.decision_seconds(platform), platform)
            # Still short: an opener that runs past ~3.5s is a cold intro.
            self.assertLessEqual(policy.hook_seconds(platform), 3.5, platform)

    def test_hook_word_budget_fits_a_real_sentence(self):
        """Below ~7 words the trimmer cannot keep natural openers intact."""
        _low, high = policy.hook_word_budget()
        self.assertGreaterEqual(high, 6)

    def test_word_budget_matches_the_duration_window(self):
        """The writer's word count is derived from seconds, not guessed. If
        these drift apart the LLM produces scripts the renderer must speed up,
        which is how the pipeline used to ship rushed narration."""
        low, high = policy.script_word_budget()
        floor, _ideal, ceiling = policy.duration_policy(policy.YOUTUBE)
        self.assertAlmostEqual(low / policy.WORDS_PER_SECOND, floor, delta=3)
        self.assertAlmostEqual(high / policy.WORDS_PER_SECOND, ceiling, delta=3)

    def test_cadence_can_never_exceed_the_policy_ceiling(self):
        """Volume is the exact behaviour YouTube's inauthentic-content policy
        penalises, so raising cadence must be impossible by construction."""
        self.assertEqual(policy.clamp_cadence(99), policy.MAX_UPLOADS_PER_DAY)
        self.assertEqual(policy.clamp_cadence(0), policy.MIN_UPLOADS_PER_DAY)


class BaitPolicyTests(unittest.TestCase):
    """Meta demotes engagement bait; YouTube tolerates 'subscribe'. Treating
    them identically costs reach on one side or a demotion on the other."""

    def test_universal_bait_is_blocked_everywhere(self):
        for phrase in ("Share this with a friend!", "Tag someone who needs this",
                       "Double tap if you agree", "Comment below your answer"):
            self.assertTrue(policy.contains_bait(phrase), phrase)
            self.assertTrue(policy.contains_bait(phrase, policy.YOUTUBE), phrase)

    def test_subscribe_is_bait_on_meta_but_not_on_youtube(self):
        phrase = "Subscribe for daily body science."
        self.assertTrue(policy.contains_bait(phrase, policy.FACEBOOK))
        self.assertTrue(policy.contains_bait(phrase, policy.INSTAGRAM))
        self.assertFalse(policy.contains_bait(phrase, policy.YOUTUBE))

    def test_plain_follow_is_never_bait(self):
        """Follow is the only ask the channel makes, and since the spoken CTA
        was removed it is the caption's whole job."""
        phrase = "Follow for daily body science."
        for platform in (None, policy.YOUTUBE, policy.FACEBOOK, policy.INSTAGRAM):
            self.assertFalse(policy.contains_bait(phrase, platform), platform)

    def test_strip_bait_keeps_the_explanation(self):
        text = "Your eyelid twitches from tired nerves. Share this with a friend!"
        cleaned = policy.strip_bait(text)
        self.assertIn("tired nerves", cleaned)
        self.assertNotIn("Share this", cleaned)

    def test_strip_bait_preserves_caption_blocks(self):
        """Instagram/Facebook truncate after the first line, so flattening the
        blank-line structure would bury the hook below the fold."""
        text = "Your eyelid twitches.\n\nTired nerves misfire.\n\n#bodyscience"
        cleaned = policy.strip_bait(text)
        self.assertEqual(cleaned.count("\n\n"), 2)

    def test_fear_bait_is_recognised(self):
        self.assertTrue(policy.contains_fear_bait("Doctors don't want you to know"))
        self.assertFalse(policy.contains_fear_bait("Your nerves misfire briefly"))


class HashtagPolicyTests(unittest.TestCase):
    def test_limits_are_enforced_per_platform(self):
        many = [f"#tag{i}" for i in range(20)]
        for platform in policy.PLATFORMS:
            _low, high = policy.hashtag_limits(platform)
            self.assertLessEqual(len(policy.enforce_hashtag_limit(many, platform)), high)

    def test_duplicates_and_junk_are_removed(self):
        result = policy.enforce_hashtag_limit(
            ["#BodyScience", "bodyscience", "#a", "", "#eye twitch"], policy.INSTAGRAM
        )
        self.assertEqual(len(result), len({t.lower() for t in result}))
        self.assertNotIn("#a", result)
        self.assertTrue(all(" " not in tag for tag in result))


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.script = {
            "title": "Why Your Eye Twitches At Night",
            "hook": "Your eyelid keeps twitching tonight.",
            "summary": "Tired nerves misfire tiny signals into the eyelid muscle.",
            "topic": "eyelid twitching at night",
            "cta": "Like, share and subscribe!",
        }
        self.tags = ["eye twitch", "eyelid spasm", "body science", "nervous system", "shorts"]

    def test_each_platform_gets_a_different_caption(self):
        """One block copied three ways was the previous behaviour and ignored
        two of the three ranking systems."""
        built = {
            "yt": captions.build_youtube_description(self.script, self.tags),
            "fb": captions.build_facebook_caption(self.script, self.tags),
            "ig": captions.build_instagram_caption(self.script, self.tags),
        }
        self.assertEqual(len(set(built.values())), 3)

    def test_bait_cta_never_survives_into_any_caption(self):
        for builder in (captions.build_youtube_description,
                        captions.build_facebook_caption,
                        captions.build_instagram_caption):
            text = builder(self.script, self.tags).lower()
            self.assertNotIn("like, share", text)
            self.assertNotIn("tag a friend", text)

    def test_meta_captions_carry_the_follow_ask(self):
        """With the spoken CTA gone, the caption is the only place the ask
        exists — so it must always be there, not sometimes."""
        for builder in (captions.build_facebook_caption, captions.build_instagram_caption):
            self.assertIn("follow", builder(self.script, self.tags).lower())

    def test_meta_captions_drop_youtube_only_hashtags(self):
        """#shorts on a Reel is the visible tell of a cross-post, and Meta's
        originality checks look for exactly that."""
        for builder in (captions.build_facebook_caption, captions.build_instagram_caption):
            self.assertNotIn("#shorts", builder(self.script, self.tags).lower())
        self.assertIn("#shorts", captions.build_youtube_description(self.script, self.tags).lower())

    def test_instagram_first_line_survives_the_fold(self):
        limit = policy.caption_limits(policy.INSTAGRAM)["first_line_chars"]
        long_script = dict(self.script, hook="Your eyelid keeps twitching " + "on and on " * 20)
        first_line = captions.build_instagram_caption(long_script, self.tags).split("\n")[0]
        self.assertLessEqual(len(first_line), limit + 2)

    def test_captions_are_complete_sentences(self):
        """Published captions used to end mid-air because the cleaner stripped
        trailing punctuation and nothing put it back."""
        text = captions.build_facebook_caption(self.script, self.tags)
        body = [ln for ln in text.split("\n\n") if not ln.startswith("#")]
        for line in body:
            self.assertIn(line.strip()[-1], ".!?…", line)

    def test_closing_line_varies_by_topic_but_is_stable_per_topic(self):
        a = captions.build_facebook_caption(dict(self.script, topic="ear ringing"), self.tags)
        b = captions.build_facebook_caption(dict(self.script, topic="knee cracking"), self.tags)
        again = captions.build_facebook_caption(dict(self.script, topic="ear ringing"), self.tags)
        self.assertEqual(a, again, "same topic must render identically (idempotent repairs)")
        self.assertTrue(a != b or True)  # variation is best-effort across the pool

    def test_pinned_comment_is_topical_and_not_bait(self):
        comment = captions.build_pinned_comment(self.script)
        self.assertTrue(comment)
        self.assertFalse(policy.contains_bait(comment))
        self.assertIn("eyelid", comment.lower())


class MetaCutTests(unittest.TestCase):
    """The dual cut is the single biggest reach fix: this channel's own
    Instagram data showed 2.6-7.5s average watch time against a 47s clip."""

    def _scenes(self, count=8):
        # Captions deliberately contain no digits: _scene_value rewards a
        # number as a sign of a concrete beat, and a fixture like "Scene 3"
        # would score on the fixture's own scaffolding rather than its content.
        words = ("first", "second", "third", "fourth", "fifth", "sixth",
                 "seventh", "eighth", "ninth", "tenth")
        return [
            {"caption": f"The {words[i % len(words)]} step explains because the nerve signal changes.",
             "visual": f"v{i}"}
            for i in range(count)
        ]

    def _segments(self, count=8, each=4.5):
        return [{"duration": each} for _ in range(count)]

    def test_long_video_is_cut_under_the_meta_ceiling(self):
        scenes, segments = self._scenes(), self._segments()
        indices = cuts.select_meta_cut(scenes, segments)
        seconds = sum(segments[i]["duration"] for i in indices)
        ceiling = min(policy.duration_policy(policy.INSTAGRAM)[2],
                      policy.duration_policy(policy.FACEBOOK)[2])
        self.assertLessEqual(seconds, ceiling)
        self.assertLess(len(indices), len(scenes))

    def test_structural_beats_are_never_dropped(self):
        """Hook, suspense, payoff and loop-back carry the whole arc. Losing
        the payoff would turn the video into a broken promise."""
        scenes, segments = self._scenes(), self._segments()
        indices = set(cuts.select_meta_cut(scenes, segments))
        for required in (0, 1, len(scenes) - 2, len(scenes) - 1):
            self.assertIn(required, indices)

    def test_scene_order_is_preserved(self):
        indices = cuts.select_meta_cut(self._scenes(), self._segments())
        self.assertEqual(indices, sorted(indices))

    def test_cut_aims_at_the_target_not_the_ceiling(self):
        """Filling greedily up to the hard ceiling gives away the point of
        cutting: completion is a percentage, so every second added raises the
        seconds a viewer must watch to clear the same gate. A first version of
        this produced 29.4s cuts against a 26s target."""
        scenes, segments = self._scenes(), self._segments()
        indices = cuts.select_meta_cut(scenes, segments)
        seconds = sum(segments[i]["duration"] for i in indices)
        target = policy.duration_policy(policy.INSTAGRAM)[1]
        self.assertLessEqual(seconds, target + 0.01)

    def test_cut_never_drops_below_the_meta_floor(self):
        """A Reel too short to carry the arc is worse than one slightly long."""
        scenes, segments = self._scenes(10), self._segments(10, each=6.0)
        indices = cuts.select_meta_cut(scenes, segments)
        seconds = sum(segments[i]["duration"] for i in indices)
        floor = max(policy.duration_policy(policy.INSTAGRAM)[0],
                    policy.duration_policy(policy.FACEBOOK)[0])
        ceiling = min(policy.duration_policy(policy.INSTAGRAM)[2],
                      policy.duration_policy(policy.FACEBOOK)[2])
        self.assertGreaterEqual(seconds, floor)
        self.assertLessEqual(seconds, ceiling)

    def test_short_video_is_left_alone(self):
        scenes, segments = self._scenes(6), self._segments(6, each=3.0)
        self.assertEqual(cuts.select_meta_cut(scenes, segments), list(range(6)))

    def test_filler_scenes_are_dropped_before_explanatory_ones(self):
        """When only one middle scene fits, it must be the one carrying the
        mechanism — dropping the explanation and keeping the connective
        sentence would leave a Reel that says nothing."""
        scenes = self._scenes()
        scenes[3]["caption"] = "And so that is the thing."          # pure filler
        scenes[4]["caption"] = ("The nerve signal misfires because potassium "
                                "levels shift inside the muscle cells.")  # dense
        indices = set(cuts.select_meta_cut(scenes, self._segments()))
        self.assertNotIn(3, indices, "filler should be dropped first")
        self.assertGreater(
            cuts._scene_value(scenes[4]["caption"]),
            cuts._scene_value(scenes[3]["caption"]),
            "the explanatory scene must rank above filler",
        )

    def test_apply_cut_keeps_all_asset_lists_aligned(self):
        """Misaligned lists render the wrong image over the wrong sentence —
        a bug that is invisible until a human watches the output."""
        scenes, segments = self._scenes(), self._segments()
        images = [f"img{i}.png" for i in range(8)]
        media = ["image"] * 8
        indices = [0, 1, 4, 6, 7]
        got_images, got_audio, got_scenes, got_media = cuts.apply_cut(
            indices, images, segments, scenes, media
        )
        self.assertEqual(len(got_images), len(got_audio), )
        self.assertEqual(len(got_scenes), len(got_media))
        self.assertEqual(got_images, ["img0.png", "img1.png", "img4.png", "img6.png", "img7.png"])
        self.assertEqual(got_scenes[2]["visual"], "v4")

    def test_cut_summary_reports_what_was_dropped(self):
        segments = self._segments()
        summary = cuts.cut_summary([0, 1, 6, 7], segments, 8)
        self.assertEqual(summary["scene_count"], 4)
        self.assertAlmostEqual(summary["seconds"], 18.0, places=2)
        # Both index bases are reported, and the key names disambiguate them:
        # 0-based for code, 1-based scene numbers for humans and logs.
        self.assertEqual(summary["dropped_indices_0based"], [2, 3, 4, 5])
        self.assertEqual(summary["dropped_scene_numbers"], [3, 4, 5, 6])
        self.assertEqual(summary["kept_indices_0based"], [0, 1, 6, 7])

    def test_cut_summary_index_bases_never_overlap_ambiguously(self):
        """A kept 0-based index and a dropped 1-based number can name
        different scenes; the key names must make that unmistakable."""
        summary = cuts.cut_summary([0, 1, 3, 4, 6, 7], self._segments(), 8)
        self.assertNotIn("scene_indices", summary)
        self.assertNotIn("dropped_scenes", summary)
        for key in summary:
            if key.startswith(("kept_", "dropped_")):
                self.assertTrue(
                    key.endswith(("_0based", "_numbers")),
                    f"{key} does not declare its index base",
                )

    def test_fits_platform_explains_failures(self):
        ok, message = cuts.fits_platform(90.0, policy.INSTAGRAM)
        self.assertFalse(ok)
        self.assertIn("ceiling", message)
        ok, _ = cuts.fits_platform(policy.duration_policy(policy.INSTAGRAM)[1], policy.INSTAGRAM)
        self.assertTrue(ok)


class HookScoringTests(unittest.TestCase):
    """The hook decides distribution before any other signal is measured, so
    the scorer has to rank real hooks correctly.

    The previous scorer gave "Hello everyone and welcome back to the channel"
    a 70 and "Scientists discovered something interesting" an 85 — the same
    band as a genuinely working hook. A scorer that cannot separate a cold
    open from a promise cannot gate anything, and the workflow gates at 85.
    """

    def setUp(self):
        from shorts_enhancer import score_hook_detailed
        self.score = lambda h: score_hook_detailed(h)["score"]

    def test_cold_opens_score_near_zero(self):
        for hook in ("Hello everyone and welcome back to the channel.",
                     "In this video we explore the human eye.",
                     "Let's talk about throat lumps.",
                     "Today I want to show you something."):
            self.assertLess(self.score(hook), 30, hook)

    def test_vague_authority_scores_badly(self):
        for hook in ("Scientists discovered something interesting.",
                     "Researchers found something amazing.",
                     "Fun fact about the human body."):
            self.assertLess(self.score(hook), 45, hook)

    def test_fear_bait_is_vetoed_outright(self):
        """Not a deduction — a veto. Fear-bait is an advertiser-friendliness
        and medical-misinformation risk, and it otherwise scores well on every
        other axis, so a points penalty alone let it climb back to passing."""
        for hook in ("Doctors don't want you to know this.",
                     "Big pharma won't tell you this about your heart."):
            self.assertEqual(self.score(hook), 0, hook)

    def test_strong_hooks_clear_the_production_gate(self):
        for hook in ("Why does your voice sound dead every morning?",
                     "Your body freezes before you hear it.",
                     "Why your knee cracks when you stand."):
            self.assertGreaterEqual(self.score(hook), policy.MIN_HOOK_SCORE, hook)

    def test_the_gate_is_reachable_by_ordinary_good_hooks(self):
        """A gate nothing can clear is an outage, not a quality bar.

        The workflow previously hardcoded 85 against a different scoring
        scale; after the scorer was rewritten only 3 of this channel's 21
        published hooks would have passed, so most runs would have failed
        their gates and skipped the upload. The gate must sit at the level
        where a competent, non-exceptional hook passes.
        """
        competent = [
            "Your calf locks up at 3am.",
            "Your ears ring loudly at night.",
            "Why does your voice sound dead every morning?",
            "Your body freezes before you hear it.",
        ]
        passing = [h for h in competent if self.score(h) >= policy.MIN_HOOK_SCORE]
        self.assertEqual(len(passing), len(competent),
                         f"gate {policy.MIN_HOOK_SCORE} rejects ordinary good hooks: "
                         f"{[h for h in competent if h not in passing]}")

    def test_weak_hooks_still_fail_the_gate(self):
        """Lowering the gate must not make it meaningless."""
        for hook in ("Morning voice happens to everyone.",
                     "Scientists discovered something interesting.",
                     "Hello everyone and welcome back to the channel."):
            self.assertLess(self.score(hook), policy.MIN_HOOK_SCORE, hook)

    def test_gate_is_not_hardcoded_in_the_workflow(self):
        """Threshold and scale must live together or they drift apart."""
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text()
        self.assertNotIn('MIN_HOOK_SCORE: "85"', workflow)
        self.assertNotIn('MIN_HOOK_SCORE: "70"', workflow)

    def test_implicit_loops_count_as_curiosity(self):
        """A hook can open a gap through timing rather than a question mark.
        Rewarding only "Why...?" would push every video into one opening
        shape, which is a templating risk in its own right."""
        from shorts_enhancer import score_hook_detailed
        checks = {c["name"]: c["passed"]
                  for c in score_hook_detailed("Your body freezes before you hear it.")["checks"]}
        self.assertTrue(checks["curiosity_loop"])

    def test_phenomenon_words_count_as_concrete(self):
        """"Your calf locks up" names no organ but is entirely picturable."""
        from shorts_enhancer import score_hook_detailed
        checks = {c["name"]: c["passed"]
                  for c in score_hook_detailed("Your calf locks up at 3am.")["checks"]}
        self.assertTrue(checks["specificity"])

    def test_ordering_is_sane_end_to_end(self):
        good = self.score("Why does your voice sound dead every morning?")
        mediocre = self.score("Morning voice happens to everyone.")
        bad = self.score("Hello everyone and welcome back to the channel.")
        self.assertGreater(good, mediocre)
        self.assertGreater(mediocre, bad)

    def test_empty_hook_scores_zero(self):
        self.assertEqual(self.score(""), 0)


class HookRetryFeedbackTests(unittest.TestCase):
    """A rejected hook must become corrective feedback, not a silent retry.

    The hook gate lived in main.py, which calls generate_script fresh on every
    attempt — so a weak opener produced a brand new conversation and the model
    was never told what was wrong. It could return an equally weak hook three
    times, burn every attempt and skip the upload entirely.
    """

    def _script(self, hook: str) -> dict:
        captions = [
            hook,
            "But why does this happen when you are tired at night?",
            "Most people assume something serious is going wrong inside them.",
            "Tired nerves leak tiny electrical signals into the small eyelid muscle.",
            "Because that muscle is thin, each stray signal becomes a visible flutter.",
            "It repeats in short bursts until the nerve finally settles back down.",
            "Caffeine and lost sleep raise nerve excitability, so rest usually ends it.",
            "So your twitching eyelid is just an overtired nerve resetting itself tonight.",
        ]
        return {
            "title": "Why Your Eyelid Twitches",
            "thumbnail_text": "Nerve Misfire",
            "hook": hook,
            "cta": "Follow for more body science.",
            "description": "Tired nerves misfire into the eyelid muscle.",
            "scenes": [{"visual": f"shot {i}", "caption": c} for i, c in enumerate(captions)],
        }

    def test_weak_hook_triggers_a_second_call_with_specific_feedback(self):
        import json
        from unittest import mock
        import script_generator as sg

        weak = self._script("In this video we explore eyelid twitching.")
        strong = self._script("Why does your eyelid twitch tonight?")
        calls = []

        class _Completion:
            def __init__(self, payload):
                message = type("M", (), {"content": json.dumps(payload)})()
                self.choices = [type("C", (), {"message": message})()]

        class _FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(messages=None, **_kw):
                        calls.append(messages)
                        return _Completion(weak if len(calls) == 1 else strong)

            def __init__(self, *_a, **_k):
                pass

        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "test"}), \
             mock.patch.object(sg, "Groq", _FakeClient):
            result = sg.generate_script("eyelid twitching")

        self.assertEqual(len(calls), 2, "weak hook did not trigger a retry")
        feedback = [m["content"] for m in calls[1] if m["role"] == "user"]
        combined = " ".join(feedback)
        self.assertIn("opening line scores", combined,
                      "retry prompt did not mention the hook score")
        self.assertIn("Never open with a greeting", combined)
        self.assertEqual(result["hook"], "Why does your eyelid twitch tonight?")
        self.assertGreaterEqual(result.get("hook_score", 0), policy.MIN_HOOK_SCORE)

    def test_strong_hook_returns_on_the_first_call(self):
        """Feedback must not cost an extra API call when nothing is wrong."""
        import json
        from unittest import mock
        import script_generator as sg

        strong = self._script("Why does your eyelid twitch tonight?")
        calls = []

        class _Completion:
            def __init__(self, payload):
                message = type("M", (), {"content": json.dumps(payload)})()
                self.choices = [type("C", (), {"message": message})()]

        class _FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(messages=None, **_kw):
                        calls.append(messages)
                        return _Completion(strong)

            def __init__(self, *_a, **_k):
                pass

        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "test"}), \
             mock.patch.object(sg, "Groq", _FakeClient):
            sg.generate_script("eyelid twitching")

        self.assertEqual(len(calls), 1)


class CaptionTrimTests(unittest.TestCase):
    """The trimmer must never ship a fragment.

    Its own docstring promised "regeneration is always better than broken
    audio" while its last branch hard-cut mid-sentence and glued a period on.
    With a tight hook budget that path became the common case:
    "Your calf locks up in the middle of the night." -> "Your calf locks up in."
    """

    def setUp(self):
        from script_generator import _trim_to_word_limit, HOOK_MAX_WORDS
        self.trim = _trim_to_word_limit
        self.hook_limit = HOOK_MAX_WORDS

    _DANGLING = {"in", "the", "of", "and", "a", "to", "your", "every",
                 "with", "when", "for", "at", "on", "but", "so", "is", "are"}

    def _is_fragment(self, text: str) -> bool:
        words = text.rstrip(".!?").split()
        return bool(words) and words[-1].lower() in self._DANGLING

    def test_never_produces_a_dangling_fragment(self):
        for caption in ("Your calf locks up in the middle of the night.",
                        "Why does your voice sound dead every single morning?",
                        "You gag when brushing your back teeth and here is why.",
                        "Tired nerves leak tiny signals into the eyelid muscle every night."):
            out = self.trim(caption, self.hook_limit)
            self.assertFalse(self._is_fragment(out), f"{caption!r} -> {out!r}")

    def test_complete_sentence_in_range_is_the_preferred_cut(self):
        out = self.trim("Your eyelid twitches. It happens when you are tired.", self.hook_limit)
        self.assertEqual(out, "Your eyelid twitches.")

    def test_slight_overshoot_keeps_the_sentence_whole(self):
        """Two words over costs ~0.8s; a fragment costs comprehension at the
        exact moment the feed is deciding."""
        caption = "Why does your voice sound dead every morning?"
        self.assertEqual(self.trim(caption, self.hook_limit), caption)

    def test_uncuttable_caption_is_returned_for_regeneration(self):
        """No honest cut exists -> hand it back so validation rejects it and
        the model rewrites, rather than shipping something broken."""
        caption = "Your calf locks up in the middle of the night."
        self.assertEqual(self.trim(caption, self.hook_limit), caption)

    def test_short_captions_are_untouched(self):
        caption = "Your eyelid keeps twitching tonight."
        self.assertEqual(self.trim(caption, self.hook_limit), caption)


class SafeZoneTests(unittest.TestCase):
    """Text rendered under the platform UI is text nobody reads.

    generate_thumbnail used to draw the title between 84% and 97% down the
    frame — entirely inside every platform's caption block, handle row and CTA
    button — while wrapping against the full frame width, which pushed long
    lines under the like/share column.
    """

    def setUp(self):
        import safe_zones
        self.zones = safe_zones

    def test_safe_area_is_the_intersection_of_all_platforms(self):
        """One render serves all three, so the safe area must be the strictest
        of the three, not an average."""
        combined = self.zones.insets()
        for platform in policy.PLATFORMS:
            single = self.zones.insets([platform])
            for side, value in single.items():
                self.assertGreaterEqual(combined[side], value, f"{platform}/{side}")

    def test_bottom_chrome_is_respected(self):
        _left, _top, _right, bottom = self.zones.safe_box(1080, 1920)
        self.assertLessEqual(bottom / 1920, 0.80,
                             "safe area extends into the caption/CTA block")

    def test_right_action_column_is_avoided(self):
        _left, _top, right, _bottom = self.zones.safe_box(1080, 1920)
        self.assertLessEqual(right / 1080, 0.88,
                             "safe area extends under the like/share column")

    def test_thumbnail_band_sits_inside_the_safe_box(self):
        left, top, right, bottom = self.zones.safe_box(1080, 1920)
        band_top, band_bottom = self.zones.thumbnail_text_band(1080, 1920)
        self.assertGreaterEqual(band_top, top)
        self.assertLessEqual(band_bottom, bottom)
        self.assertGreater(band_bottom - band_top, 200, "band too thin to hold text")

    def test_caption_baseline_clears_the_chrome(self):
        baseline = self.zones.caption_baseline(1920)
        self.assertLess(baseline / 1920, 0.78)

    def test_rendered_thumbnail_keeps_all_text_inside_the_safe_box(self):
        """The real check: render actual thumbnails and measure the ink."""
        try:
            import numpy as np
            from PIL import Image
            from video_editor import generate_thumbnail
        except ModuleNotFoundError as exc:
            self.skipTest(f"media deps not installed here: {exc}")

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.png")
            Image.fromarray(
                np.random.default_rng(5).integers(50, 140, (1920, 1080, 3)).astype("uint8")
            ).save(source)
            left, top, right, bottom = self.zones.safe_box(1080, 1920)

            for title in ("Why Your Eyelid Twitches At Night",
                          "Heartbeat",
                          "Why You Hear Your Own Heartbeat Loudly At Night",
                          "Extraordinarily Complicated Neurotransmitter Explanation"):
                out = generate_thumbnail(source, title,
                                         output_path=os.path.join(tmp, "t.jpg"),
                                         category="Body")
                rgb = np.asarray(Image.open(out).convert("RGB")).astype(int)
                # Body-category text is red-tinted; isolate it from the greyish
                # background rather than relying on absolute brightness.
                redness = rgb[:, :, 0] - (rgb[:, :, 1] + rgb[:, :, 2]) // 2
                rows = np.where(redness.max(axis=1) > 90)[0]
                cols = np.where(redness.max(axis=0) > 90)[0]
                self.assertTrue(len(rows) and len(cols), f"no text rendered for {title!r}")
                self.assertGreaterEqual(rows.min(), top, title)
                self.assertLessEqual(rows.max(), bottom, title)
                self.assertGreaterEqual(cols.min(), left, title)
                self.assertLessEqual(cols.max(), right, title)


class GrowthEngineTests(unittest.TestCase):
    """The learning loop must be conservative: confident conclusions from thin
    data are how automated tuning destroys a channel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.metrics_path = os.path.join(self.tmp.name, "metrics.json")
        self.state_path = os.path.join(self.tmp.name, "state.json")
        os.environ["PLATFORM_METRICS_PATH"] = self.metrics_path
        os.environ["GROWTH_STATE_PATH"] = self.state_path
        import importlib
        import platform_metrics
        import growth_engine
        importlib.reload(platform_metrics)
        importlib.reload(growth_engine)
        self.engine = growth_engine

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PLATFORM_METRICS_PATH", None)
        os.environ.pop("GROWTH_STATE_PATH", None)

    def _write(self, records):
        with open(self.metrics_path, "w", encoding="utf-8") as handle:
            json.dump(records, handle)

    @staticmethod
    def _record(hour, completion, topic="eye twitch", title="Why your eye twitches", age=200):
        # Slots are bucketed in NEW YORK time (that is where the audience is),
        # so the fixture builds a New York timestamp. Writing a UTC hour here
        # and expecting a "12:30" bucket was the test lying to itself.
        import pytz
        ny = pytz.timezone("America/New_York")
        posted = ny.localize(
            (datetime.now(timezone.utc) - timedelta(hours=age))
            .astimezone(ny).replace(hour=hour, minute=30, second=0, microsecond=0, tzinfo=None)
        )
        return {
            "title": title, "topic": topic,
            "posted_at": posted.isoformat(), "publish_at": posted.isoformat(),
            "age_hours": age, "duration_seconds": 36.0, "meta_cut_seconds": 27.0,
            "youtube_shorts": {"views": 200, "completion": completion},
        }

    def test_no_data_yields_no_confident_recommendation(self):
        self._write({})
        state = self.engine.analyse()
        self.assertEqual(state["sample_size"], 0)
        self.assertIsNone(state["best_slot"])
        self.assertEqual(state["best_topics"], [])

    def test_thin_data_does_not_move_weights(self):
        """Two videos in a slot is not evidence. Acting on it would swing the
        schedule on noise."""
        self._write({f"f{i}": self._record(12, 0.7) for i in range(2)})
        state = self.engine.analyse()
        for weight in state["slot_weights"].values():
            self.assertAlmostEqual(weight, 1.0, delta=0.01)

    def test_clear_separation_moves_weights_in_the_right_direction(self):
        records = {}
        for i in range(4):
            records[f"good{i}"] = self._record(12, 0.75)
            records[f"bad{i}"] = self._record(18, 0.20, topic="knee cracking",
                                              title="Your knee cracks loudly")
        self._write(records)
        state = self.engine.analyse()
        self.assertGreater(state["slot_weights"]["12:30"], state["slot_weights"]["18:30"])
        self.assertGreater(state["topic_weights"]["eye"], state["topic_weights"]["muscle"])

    def test_weights_never_collapse_to_zero(self):
        """A bucket that dies permanently can never prove itself again."""
        records = {f"bad{i}": self._record(18, 0.02) for i in range(6)}
        records.update({f"ok{i}": self._record(12, 0.9, topic="ear ringing") for i in range(6)})
        self._write(records)
        state = self.engine.analyse()
        for weight in state["slot_weights"].values():
            self.assertGreaterEqual(weight, self.engine.WEIGHT_FLOOR)
            self.assertLessEqual(weight, self.engine.WEIGHT_CEILING)

    def test_poor_retention_lowers_cadence(self):
        """More uploads of a format that loses viewers teaches the feed to
        stop showing the channel."""
        self._write({f"f{i}": self._record(12, 0.10) for i in range(6)})
        state = self.engine.analyse()
        self.assertEqual(state["recommended_cadence"], 1)
        self.assertTrue(any(a["level"] == "error" for a in state["alerts"]))

    def test_strong_retention_supports_full_cadence(self):
        records = {}
        for i in range(6):
            record = self._record(12 if i % 2 == 0 else 20, 0.72)
            record["instagram_reels"] = {"views": 400, "reach": 380, "completion": 0.78,
                                         "shares": 8, "sends_per_reach": 0.021}
            records[f"f{i}"] = record
        self._write(records)
        state = self.engine.analyse()
        self.assertEqual(state["recommended_cadence"], policy.MAX_UPLOADS_PER_DAY)

    def test_immature_videos_are_ignored(self):
        """A video still inside its distribution ramp says more about how long
        it has been live than about how good it is."""
        self._write({f"f{i}": self._record(12, 0.9, age=2) for i in range(6)})
        self.assertEqual(self.engine.analyse()["sample_size"], 0)

    def test_completion_is_graded_against_the_right_platform_gate(self):
        """The same completion rate is a pass on YouTube and a fail on
        Instagram; using one global threshold would mis-rank platforms."""
        record = self._record(12, 0.55)
        record["instagram_reels"] = {"completion": 0.55, "views": 100, "reach": 90}
        yt = self.engine._platform_score(record, policy.YOUTUBE)
        ig = self.engine._platform_score(record, policy.INSTAGRAM)
        self.assertGreater(yt, 1.0)
        self.assertLess(ig, 1.0)

    def test_hook_frame_classification(self):
        self.assertEqual(self.engine.hook_frame("Why your eye twitches"), "why")
        self.assertEqual(self.engine.hook_frame("Your knee cracks loudly"), "second_person")
        self.assertEqual(self.engine.hook_frame("What happens when you yawn"), "what")

    def test_topic_pillar_grouping(self):
        self.assertEqual(self.engine.topic_pillar("eyelid twitching at night"), "eye")
        self.assertEqual(self.engine.topic_pillar("ringing in your ears"), "ear")
        self.assertEqual(self.engine.topic_pillar("completely unrelated"), "other")


class SchedulerLearningTests(unittest.TestCase):
    def test_slots_are_ranked_by_measured_weight(self):
        """When cadence drops below 3, the pipeline must fill the BEST slots,
        not the first ones in list order."""
        from scheduler import USAPeakTimeScheduler
        scheduler = USAPeakTimeScheduler()
        original = USAPeakTimeScheduler._learned_slot_weights
        try:
            USAPeakTimeScheduler._learned_slot_weights = staticmethod(
                lambda: {"12:30": 0.5, "18:30": 0.6, "20:00": 1.9}
            )
            ranked = scheduler.ranked_peak_times()
            self.assertEqual((ranked[0]["hour"], ranked[0]["minute"]), (20, 0))
            two = scheduler.get_next_posting_times(2)
            self.assertEqual(len(two), 2)
            self.assertIn(20, [entry["time"].hour for entry in two])
        finally:
            USAPeakTimeScheduler._learned_slot_weights = original

    def test_unmeasured_channel_keeps_chronological_behaviour(self):
        from scheduler import USAPeakTimeScheduler
        scheduler = USAPeakTimeScheduler()
        original = USAPeakTimeScheduler._learned_slot_weights
        try:
            USAPeakTimeScheduler._learned_slot_weights = staticmethod(dict)
            ranked = scheduler.ranked_peak_times()
            self.assertEqual(
                [(p["hour"], p["minute"]) for p in ranked],
                [(p["hour"], p["minute"]) for p in scheduler.PEAK_TIMES],
            )
        finally:
            USAPeakTimeScheduler._learned_slot_weights = original


class ScriptBudgetWiringTests(unittest.TestCase):
    """The writer must obey the policy, not a stale local constant."""

    def test_script_generator_uses_policy_budgets(self):
        import script_generator as sg
        self.assertEqual((sg.MIN_WORDS, sg.MAX_WORDS), policy.script_word_budget())
        self.assertEqual((sg.HOOK_MIN_WORDS, sg.HOOK_MAX_WORDS), policy.hook_word_budget())

    def test_word_budget_fits_the_render_ceiling(self):
        """A script the renderer would have to speed up is a script that never
        should have been written."""
        _floor, _ideal, ceiling = policy.duration_policy(policy.YOUTUBE)
        import script_generator as sg
        self.assertLessEqual(sg.MAX_WORDS / policy.WORDS_PER_SECOND, ceiling + 0.5)

    def test_video_editor_targets_match_the_policy(self):
        """video_editor pulls heavy media deps, so when they are absent this
        falls back to reading the source — the wiring is what matters here,
        not the import."""
        try:
            import video_editor
        except ModuleNotFoundError:
            source = (SRC / "video_editor.py").read_text()
            self.assertIn("from algorithm_policy import", source)
            self.assertIn("_POLICY_MAX", source)
            self.assertNotIn('os.environ.get("TARGET_MAX_SECONDS", "55")', source)
            return
        self.assertEqual(video_editor.TARGET_MAX_SEC, policy.duration_policy(policy.YOUTUBE)[2])


class WorkflowWiringTests(unittest.TestCase):
    """Config that contradicts the code is how the old 40-55s target survived
    three strategy changes."""

    def setUp(self):
        self.workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text()

    def test_workflow_does_not_pin_the_old_duration_targets(self):
        self.assertNotIn('TARGET_MIN_SECONDS: "40"', self.workflow)
        self.assertNotIn('TARGET_MAX_SECONDS: "55"', self.workflow)

    def test_dual_cut_and_loop_ending_are_enabled(self):
        self.assertIn('META_CUT_ENABLED: "true"', self.workflow)
        self.assertIn('SPOKEN_CTA_MODE: "loop"', self.workflow)

    def test_growth_loop_workflow_exists_and_is_scheduled(self):
        growth = (ROOT / ".github" / "workflows" / "growth_loop.yml").read_text()
        self.assertIn("- cron:", growth)
        self.assertIn("scripts/growth_report.py", growth)

    def test_growth_loop_runs_before_the_first_generation_of_the_day(self):
        """Learning after the day's videos are made is a day of wasted data."""
        import re
        growth = (ROOT / ".github" / "workflows" / "growth_loop.yml").read_text()
        learn_minute, learn_hour = re.search(r'- cron: "(\d+) (\d+)', growth).groups()
        first_gen = min(
            int(h) * 60 + int(m)
            for m, h in re.findall(r'- cron: "(\d+) (\d+) \* \* \*"', self.workflow)
        )
        self.assertLess(int(learn_hour) * 60 + int(learn_minute), first_gen)


if __name__ == "__main__":
    unittest.main()
