from __future__ import annotations

from src.content import fallback
from src.seo import build_packages


def test_platform_seo_is_separate():
    packages = build_packages(fallback('Why does memory feel familiar?'))
    assert set(packages) == {'youtube', 'facebook', 'instagram'}
    assert packages['youtube']['tags']
    assert '#shorts' in packages['youtube']['description'].lower()
    assert packages['facebook']['description'] != packages['youtube']['description']


def test_instagram_package_carries_reels_hashtag():
    """Hashtags live in the instagram package's `hashtags` list, not inside `caption`.

    meta.publish joins them onto the caption at publish time. The previous version of
    this test asserted '#reels' in packages['instagram']['caption'], which the code has
    never produced — so the assertion could not pass, and it gated production.
    """
    packages = build_packages(fallback('Why does memory feel familiar?'))
    hashtags = [tag.lower() for tag in packages['instagram']['hashtags']]
    assert '#reels' in hashtags
    assert packages['instagram']['caption']
