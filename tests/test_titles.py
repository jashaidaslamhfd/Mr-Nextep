"""Title validation regressions.

Every rejected title in this file is one the channel actually published. The old
us_title_for_short hard-truncated at 50 chars and appended " #Shorts" to the stump, and
the trend scraper prepended "Why does " to raw news headlines, so these are real outputs
rather than invented edge cases.
"""
from __future__ import annotations

import pytest

from src.utils import SHORTS_TITLE_MAX_CHARS, TitleRejected, us_title_for_short, validate_short_title

# Real titles from data/content_history.json before this change.
PUBLISHED_BAD_TITLES = [
    "Why does apple acquires brain imaging firm for health and accessibilit",
    "Why does overnight Therapy? The Role of Sleep in Emotional Brain Proce",
    "Why does writer's Enterprise Brain Adds Shared Memory For Agents?",
    "Why does wisconsin health officials stress importance of vaccines as s",
    "Why some fails in life",
]


@pytest.mark.parametrize("title", PUBLISHED_BAD_TITLES)
def test_previously_published_titles_are_now_rejected(title):
    with pytest.raises(TitleRejected):
        validate_short_title(title)


def test_over_length_title_is_rejected_not_truncated():
    """The core fix: too long means regenerate, never cut a word in half."""
    long_title = "The dark neuroscience of why your brain invents shadows at night"
    assert len(long_title) > SHORTS_TITLE_MAX_CHARS
    with pytest.raises(TitleRejected) as exc:
        validate_short_title(long_title)
    assert "shorter" in str(exc.value)


def test_valid_title_passes_through_unchanged():
    assert validate_short_title("Why does silence feel loud?") == "Why does silence feel loud?"


def test_whitespace_is_collapsed():
    assert validate_short_title("Why  does   silence feel loud?") == "Why does silence feel loud?"


def test_spliced_headline_is_rejected():
    with pytest.raises(TitleRejected) as exc:
        validate_short_title("Why does Apple acquires a firm?")
    assert "base verb form" in str(exc.value)


def test_two_sentences_are_rejected():
    with pytest.raises(TitleRejected) as exc:
        validate_short_title("Sleep resets memory. The reason?")
    assert "more than one sentence" in str(exc.value)


def test_interrogative_without_question_mark_is_rejected():
    with pytest.raises(TitleRejected):
        validate_short_title("Why your brain invents shadows")


def test_dangling_tail_word_is_rejected():
    with pytest.raises(TitleRejected) as exc:
        validate_short_title("The strange reason your brain is")
    assert "cut off" in str(exc.value)


def test_hashtag_inside_title_is_rejected():
    with pytest.raises(TitleRejected):
        validate_short_title("Why silence feels loud #Shorts")


def test_ellipsis_is_rejected():
    with pytest.raises(TitleRejected):
        validate_short_title("Why your brain invents shadows...")


def test_scraped_source_separator_is_rejected():
    with pytest.raises(TitleRejected):
        validate_short_title("Sleep clears brain waste - Reuters")


def test_too_few_words_is_rejected():
    with pytest.raises(TitleRejected):
        validate_short_title("Brain glitch")


def test_hashtag_is_appended_only_when_it_fits():
    short = us_title_for_short("Why does silence feel loud?")
    assert short == "Why does silence feel loud? #Shorts"
    assert len(short) <= SHORTS_TITLE_MAX_CHARS


def test_hashtag_is_dropped_rather_than_truncating_the_title():
    """A 45-char title has no room for " #Shorts". The title wins, not the tag."""
    title = "Why does your body jolt as you fall asleep?"
    packaged = us_title_for_short(title)
    assert packaged == title
    assert "#Shorts" not in packaged
    assert len(packaged) <= SHORTS_TITLE_MAX_CHARS
