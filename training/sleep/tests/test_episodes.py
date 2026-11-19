import numpy as np
from episodes import extract, merge, runs, segment_episodes, segments, to_minutes


def day(*sleeps):
    """One day row (144 bins) from (start_min, end_min) sleeps; minutes may fall inside a bin."""
    m = np.zeros(1440)
    for s, e in sleeps:
        m[s:e] = 1
    return m.reshape(144, 10).mean(axis=1)


def test_partial_bins_go_next_to_the_asleep_side():
    bins = np.array([0, 0.3, 1, 1, 0.6, 0])  # asleep 07:-27 .. 46 in minutes
    a = to_minutes(bins)
    assert runs(a).tolist() == [[17, 46]]
    assert runs(to_minutes(np.array([0, 0.4, 0]))).tolist() == [[13, 17]]  # isolated: middle of the bin


def test_merge_short_wake_and_drop_tiny_sleep():
    ep = np.array([[0, 60], [70, 120], [200, 203], [300, 400]])
    assert merge(ep).tolist() == [[0, 120], [300, 400]]  # 10-min gap merged; 3-min sleep dropped


def test_segments_split_on_missing_days():
    obs = np.array([True, True, False, True])
    assert segments(obs) == [(0, 2), (3, 1)]


def test_episode_across_midnight_and_censoring():
    rows = np.stack([day((0, 360), (1140, 1440)), day((0, 400), (780, 870))])
    df = segment_episodes(rows, first_day=5)
    assert df[["start", "end"]].values.tolist() == [[7200, 7560], [8340, 9040], [9420, 9510]]
    assert df.cens_start.tolist() == [True, False, False]


def test_extract_nights_naps_and_events():
    # 4 days: night 19:30-06:30 with one waking 01:00-01:30; naps 09:00-10:00 and 13:00-14:30.
    one = day((0, 60), (90, 390), (540, 600), (780, 870), (1170, 1440))
    data = np.full((6, 144, 1), np.nan)
    data[1:5, :, 0] = one
    ep, days, events, stats = extract(data)
    assert stats["night_waking_transitions"] == 3  # one waking in each of the 3 inner nights
    d = days.iloc[0]
    assert (d.wake, d.bedtime, d.naps, d.day_sleep, d.night_wakings) == (390, 1170, 2, 150, 1)
    assert d.night_sleep == 330 + 300 and d.longest_night == 330  # 19:30-01:00 joins across midnight
    ev = events[events.day == d.day]
    assert ev.kind.tolist() == ["nap", "nap", "bedtime"]
    assert ev.ww.tolist() == [150, 180, 300] and ev.position.tolist() == [1, 2, 0]
