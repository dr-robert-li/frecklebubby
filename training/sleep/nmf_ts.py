"""Step 3: NMF with time smoothing (Liu et al. 2019, appendix B.1) and kernel-regression forecasts (C.3-C.4).

Usage: python nmf_ts.py DATA.mat OUT_DIR FIG_DIR [ITERATIONS]

Problem (paper eq. 3): minimise sum ||Y - C F||^2 + lambda * sum ||D C_j||^2, C >= 0, F >= 0, ||F_j||_2 = 1,
rank 5, lambda = 1e5, D = second-order finite difference with Neumann ends (authors' generate_finite_diff.m).
Like the authors' code, each run of consecutive observed days (a segment) is smoothed on its own.

Changes from the authors' Matlab (lsqlin):
- Coefficient step: ADMM in place of lsqlin. The C-subproblem C(2FF'+rho I) + 2 lambda L'L C = R is solved exactly:
  L'L is diagonal in the orthonormal DCT-II basis (Neumann Laplacian), 2FF'+rho I by a 5x5 eigendecomposition.
  ADMM state is kept between outer iterations (warm start), with ADMM_STEPS steps per outer iteration.
- Basis step: exact non-negative least squares per time bin (scipy nnls on the 5x5 Gram matrix).
- Initialisation: scikit-learn NMF on a random 60 000-day sample in place of Matlab nnmf on all days.
- Fixed number of outer iterations (default 200) in place of the 1e-6 relative-change stop at up to 1000.
Output: nmf_basis.npy (5 x 144, shared patterns, no per-infant data), figures, nmf_stats.json.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from episodes import load, segments
from scipy.fft import dct, idct
from scipy.optimize import nnls
from scipy.spatial.distance import pdist
from sklearn.decomposition import NMF

R, LAM, RHO, ADMM_STEPS = 5, 1e5, 5.0, 25


class Model:
    def __init__(self, data: np.ndarray, infants=None, rng=0):
        self.infants = list(range(data.shape[2])) if infants is None else list(infants)
        rows, segs = [], []  # segs: (infant, first_day, n_days, row offset)
        off = 0
        for n in self.infants:
            for first, m in segments(~np.isnan(data[:, 0, n])):
                if m < 2:
                    continue
                rows.append(data[first:first + m, :, n])
                segs.append((n, first, m, off))
                off += m
        self.Y = np.concatenate(rows)
        self.segs = segs
        self.by_len: dict[int, np.ndarray] = {}
        for m in sorted({s[2] for s in segs}):
            offs = np.array([s[3] for s in segs if s[2] == m])
            self.by_len[m] = offs[:, None] + np.arange(m)[None, :]
        g = np.random.default_rng(rng)
        sample = self.Y[g.choice(len(self.Y), min(60000, len(self.Y)), replace=False)]
        nmf = NMF(R, init="nndsvda", max_iter=300, random_state=rng).fit(sample)
        self.F = nmf.components_
        self.C = np.zeros((len(self.Y), R))
        self.Z = np.zeros_like(self.C)
        self.U = np.zeros_like(self.C)
        self._normalise()

    def _normalise(self):
        s = np.linalg.norm(self.F, axis=1)
        s[s == 0] = 1
        self.F /= s[:, None]
        for x in (self.C, self.Z, self.U):
            x *= s[None, :]

    def update_c(self, steps=ADMM_STEPS):
        F = self.F
        b, P = np.linalg.eigh(2 * F @ F.T + RHO * np.eye(R))
        YF2 = 2 * self.Y @ F.T
        for m, idx in self.by_len.items():
            a = 2 * LAM * (2 - 2 * np.cos(np.pi * np.arange(m) / m)) ** 2
            den = a[None, :, None] + b[None, None, :]
            Z, U, base = self.Z[idx], self.U[idx], YF2[idx]
            for _ in range(steps):
                T = dct((base + RHO * (Z - U)) @ P, type=2, norm="ortho", axis=1)
                C = idct(T / den, type=2, norm="ortho", axis=1) @ P.T
                Z = np.maximum(C + U, 0)
                U = U + C - Z
            self.C[idx], self.Z[idx], self.U[idx] = Z, Z, U  # keep the feasible copy

    def update_f(self):
        G = self.C.T @ self.C + 1e-9 * np.eye(R)
        Lc = np.linalg.cholesky(G)  # G = Lc Lc'
        H = self.C.T @ self.Y
        q = np.linalg.solve(Lc, H)
        self.F = np.stack([nnls(Lc.T, q[:, i])[0] for i in range(self.Y.shape[1])], axis=1)
        self._normalise()

    def objective(self) -> tuple[float, float]:
        fit = float(((self.Y - self.C @ self.F) ** 2).sum())
        reg = 0.0
        for idx in self.by_len.values():
            Cs = self.C[idx]
            d = np.diff(Cs, 2, axis=1)
            reg += float((d ** 2).sum() + ((Cs[:, 1] - Cs[:, 0]) ** 2).sum() + ((Cs[:, -1] - Cs[:, -2]) ** 2).sum())
        return fit, LAM * reg

    def fit(self, iters: int, log=print):
        self.update_c(steps=100)
        for it in range(iters):
            self.update_f()
            self.update_c()
            if it % 10 == 0 or it == iters - 1:
                fit, reg = self.objective()
                log(f"it {it} fit {fit:.0f} smooth {reg:.0f} total {fit + reg:.0f}")
        return self

    def coefficients_3d(self, n_days: int) -> np.ndarray:
        """(day, component, infant-in-model) with NaN on missing days."""
        out = np.full((n_days, R, len(self.infants)), np.nan)
        pos = {n: i for i, n in enumerate(self.infants)}
        for n, first, m, off in self.segs:
            out[first:first + m, :, pos[n]] = self.C[off:off + m]
        return out


def coef_for(Y: np.ndarray, F: np.ndarray, steps=300) -> np.ndarray:
    """Smoothed non-negative coefficients of one segment for a fixed basis."""
    m = len(Y)
    b, P = np.linalg.eigh(2 * F @ F.T + RHO * np.eye(R))
    a = 2 * LAM * (2 - 2 * np.cos(np.pi * np.arange(m) / m)) ** 2
    den = a[:, None] + b[None, :]
    base = 2 * Y @ F.T
    Z = U = np.zeros((m, R))
    for _ in range(steps):
        C = idct(dct((base + RHO * (Z - U)) @ P, type=2, norm="ortho", axis=0) / den, type=2, norm="ortho", axis=0) @ P.T
        Z = np.maximum(C + U, 0)
        U = U + C - Z
    return Z


def window_coef(x: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Coefficients for a window of days (rows may be NaN): each observed run on its own, then linear interpolation
    over missing days (shortcut: the paper does not say how it fills gaps for the forecast)."""
    out = np.full((len(x), R), np.nan)
    for first, m in segments(~np.isnan(x[:, 0])):
        out[first:first + m] = coef_for(x[first:first + m], F) if m > 1 else nnls_row(x[first], F)
    ok = ~np.isnan(out[:, 0])
    t = np.arange(len(x))
    return np.stack([np.interp(t, t[ok], out[ok, j]) for j in range(R)], axis=1)


def nnls_row(y, F):
    return nnls(F.T, y)[0][None, :]


def forecast(data: np.ndarray, F_train: np.ndarray, train: list[int], test: list[int]) -> list[dict]:
    """Table 1: forecast days [a+100, a+200) from days [a, a+100) for infants with >= 70 % of both observed."""
    rows = []
    for a, b in ((0, 100), (200, 300), (500, 600)):
        fut = (b, b + 100)

        def ok(n):
            o = ~np.isnan(data[:, 0, n])
            return o[a:b].mean() >= 0.7 and o[fut[0]:fut[1]].mean() >= 0.7  # noqa: B023

        tr = [n for n in train if ok(n)]
        te = [n for n in test if ok(n)]
        past = {n: window_coef(data[a:b, :, n], F_train) for n in tr + te}
        futc = {n: window_coef(data[fut[0]:fut[1], :, n], F_train) for n in tr + te}
        Xp = np.stack([past[n].ravel() for n in tr])
        Xf = np.stack([futc[n] for n in tr])
        Ytr = data[fut[0]:fut[1], :, tr]
        mean = np.nanmean(Ytr, axis=2)
        mean = np.where(np.isnan(mean), np.nanmean(Ytr), mean)
        raw_p = np.stack([np.nan_to_num(data[a:b, :, n], nan=np.nanmean(data[a:b, :, n])).ravel() for n in tr])
        raw_f = np.stack([np.nan_to_num(data[fut[0]:fut[1], :, n], nan=0.5) for n in tr])

        def kr(X, Yf, x, sigma, skip=None):
            d2 = ((X - x) ** 2).sum(1)
            w = np.exp(-(d2 - d2.min()) / (2 * sigma ** 2))
            if skip is not None:
                w[skip] = 0
            return np.tensordot(w / w.sum(), Yf, axes=1)

        def cv_sigma(X, Yf, target):
            med = float(np.median(pdist(X)))
            best = None
            for f in (0.05, 0.1, 0.2, 0.3, 0.5, 1, 2):
                err = np.mean([np.nanmean(np.abs(target(kr(X, Yf, X[i], f * med, skip=i), i)))
                               for i in range(len(X))])
                if best is None or err < best[0]:
                    best = (err, f * med)
            return best[1]

        dat = lambda n: data[fut[0]:fut[1], :, n]  # noqa: E731, B023
        s_nmf = cv_sigma(Xp, Xf, lambda c, i: c @ F_train - dat(tr[i]))  # noqa: B023
        s_raw = cv_sigma(raw_p, raw_f, lambda y, i: y - dat(tr[i]))  # noqa: B023
        errs = {"Mean": [], "KR (raw data)": [], "KR (NMF-TS)": [], "Rank-5 ground truth": []}
        sq = {k: [] for k in errs}
        for n in te:
            y = dat(n)
            preds = {
                "Mean": mean,
                "KR (raw data)": kr(raw_p, raw_f, np.nan_to_num(data[a:b, :, n], nan=np.nanmean(data[a:b, :, n])).ravel(), s_raw),
                "KR (NMF-TS)": kr(Xp, Xf, past[n].ravel(), s_nmf) @ F_train,
                "Rank-5 ground truth": futc[n] @ F_train,
            }
            for k, p in preds.items():
                errs[k].append(np.nanmean(np.abs(p - y)))
                sq[k].append(np.sqrt(np.nanmean((p - y) ** 2)))
        rows.append({"period": f"{fut[0]}-{fut[1]} from {a}-{b}", "n_train": len(tr), "n_test": len(te),
                     "mae": {k: [round(float(np.mean(v)), 3), round(float(np.std(v)), 3)] for k, v in errs.items()},
                     "rmse": {k: [round(float(np.mean(v)), 3), round(float(np.std(v)), 3)] for k, v in sq.items()}})
        print(rows[-1])
    return rows


def figures(model: Model, data_days: int, fig_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    C3 = model.coefficients_3d(data_days)
    hours = np.arange(144) / 6
    fig, axes = plt.subplots(R, 2, figsize=(10, 2.2 * R))
    for j in range(R):
        axes[j, 0].plot(hours, model.F[j])
        axes[j, 0].set(xlim=(0, 24), ylabel=f"F{j + 1}")
        q = np.nanpercentile(C3[:, j, :], [10, 25, 50, 75, 90], axis=1)
        for k, lab in enumerate(("10%", "25%", "Median", "75%", "90%")):
            axes[j, 1].plot(np.arange(data_days), q[k], lw=0.8, label=lab)
    axes[-1, 0].set_xlabel("Time of day (hours)")
    axes[-1, 1].set_xlabel("Age (days)")
    axes[0, 1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "nmf_ts_figure2.png", dpi=120)
    plt.close(fig)


def main(mat: str, out: str, fig_dir: str, iters: str = "200") -> None:
    data = load(mat)
    out_dir, figs = Path(out), Path(fig_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    model = Model(data).fit(int(iters))
    np.save(out_dir / "nmf_basis.npy", model.F)
    figures(model, data.shape[0], figs)
    fit, reg = model.objective()
    stats = {"iterations": int(iters), "seconds_full_fit": round(time.time() - t0), "fit": fit, "smooth": reg}
    # Forecasting (Table 1): 561 train / 140 test infants (the paper's split sizes; random split, seed 2019).
    perm = np.random.default_rng(2019).permutation(data.shape[2])
    train, test = sorted(perm[: int(0.8 * len(perm))].tolist()), sorted(perm[int(0.8 * len(perm)):].tolist())
    mt = Model(data, infants=train).fit(int(iters))
    stats["forecast"] = forecast(data, mt.F, train, test)
    (out_dir / "nmf_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:5])
