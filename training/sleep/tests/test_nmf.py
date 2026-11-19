import nmf_ts
import numpy as np
from scipy.optimize import lsq_linear


def test_coefficient_step_matches_bounded_least_squares():
    g = np.random.default_rng(1)
    m, r = 15, nmf_ts.R
    F = np.abs(g.normal(size=(r, 144)))
    F /= np.linalg.norm(F, axis=1)[:, None]
    Y = np.clip(np.abs(g.normal(size=(m, r))) @ F + 0.1 * g.normal(size=(m, 144)), 0, 1)
    L = 2 * np.eye(m) - np.eye(m, k=1) - np.eye(m, k=-1)
    L[0, 0] = L[-1, -1] = 1
    # vec(C) column-major: Y ~ C F  <=>  (F' kron I) vec(C)
    A = np.vstack([np.kron(F.T, np.eye(m)), np.sqrt(nmf_ts.LAM) * np.kron(np.eye(r), L)])
    b = np.r_[Y.T.ravel(), np.zeros(m * r)]
    ref = lsq_linear(A, b, bounds=(0, np.inf), tol=1e-12).x.reshape(r, m).T
    got = nmf_ts.coef_for(Y, F, steps=3000)
    assert np.abs(got - ref).max() < 1e-2 * max(1, np.abs(ref).max())
