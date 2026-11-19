import json

import replay_app_db as R
from tests.test_app_equivalence import made_up_norms


def test_replay_on_synthetic_database(tmp_path, monkeypatch):
    db, cid = R.make_synthetic(tmp_path)
    norms = tmp_path / "norms.json"
    norms.write_text(json.dumps(made_up_norms()))
    out = R.replay(db, str(cid), norms)
    assert set(out) == {"a", "b", "c"}
    assert all(out[m]["n"] > 80 for m in out)
    # The child keeps a steady pattern, so its own history must help: c beats the age norms alone.
    assert out["c"]["mae"] < out["b"]["mae"]
    assert 0 <= out["c"]["interval_coverage"] <= 1
    print(out)
