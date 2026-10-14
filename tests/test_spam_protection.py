from pokevent.spam_protection import SpamDetector


def test_detects_rapid_messages_across_three_channels() -> None:
    detector = SpamDetector()
    for index, channel_id in enumerate((10, 11, 10, 12), start=1):
        assert not detector.observe(1, 99, channel_id, index, now=float(index)).blocked

    decision = detector.observe(1, 99, 12, 5, now=5.5)
    assert decision.blocked and decision.newly_triggered
    assert decision.message_count == 5
    assert decision.channel_count == 3
    assert decision.targets == ((10, 1), (11, 2), (10, 3), (12, 4), (12, 5))

    subsequent = detector.observe(1, 99, 20, 6, now=6.0)
    assert subsequent.blocked and not subsequent.newly_triggered
    assert subsequent.targets == ((20, 6),)


def test_one_channel_flood_is_not_mistaken_for_cross_channel_spam() -> None:
    detector = SpamDetector()
    for index in range(30):
        assert not detector.observe(1, 99, 10, index, now=1.0 + index / 10).blocked


def test_old_messages_and_other_guilds_do_not_contribute() -> None:
    detector = SpamDetector()
    for index in range(4):
        assert not detector.observe(1, 99, 10 + index, index, now=float(index)).blocked
    assert not detector.observe(1, 99, 15, 10, now=40.0).blocked

    for index in range(4):
        assert not detector.observe(2, 99, index, index, now=41.0).blocked
    assert not detector.observe(1, 99, index, 100 + index, now=41.0).blocked


def test_enforcement_expires_or_can_be_cleared_when_disabled() -> None:
    detector = SpamDetector()
    for index, channel_id in enumerate((1, 2, 3, 1, 2)):
        decision = detector.observe(1, 99, channel_id, index, now=100.0 + index)
    assert decision.newly_triggered
    assert detector.observe(1, 99, 9, 10, now=200.0).blocked

    detector.clear_guild(1)
    assert not detector.observe(1, 99, 9, 11, now=201.0).blocked

    for index, channel_id in enumerate((1, 2, 3, 1, 2)):
        decision = detector.observe(1, 99, channel_id, index + 20, now=300.0 + index)
    assert decision.newly_triggered
    assert not detector.observe(1, 99, 9, 100, now=1000.0).blocked
