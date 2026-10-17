"""How shocks spread between markets: Diebold-Yilmaz (2012) connectedness.

A VAR describes how each market's move depends on yesterday's moves in all markets. The generalized
forecast-error variance decomposition (Pesaran & Shin 1998) then answers, for each market i:
"what share of the uncertainty in i's H-day-ahead forecast is due to shocks that start in market j?"
That matrix is a weighted, directed network: who infects whom, and how strongly.

  theta[i, j]   share of i's forecast-error variance coming from j (rows sum to 1)
  total         average share coming from other markets (0-100%): how contagious the system is
  to[j], from[i], net = to - from: who transmits, who receives
"""
import numpy as np


# ---------- VAR(p) by OLS ----------

def _lagged(Y, p):
    T = len(Y)
    X = np.hstack([np.ones((T - p, 1))] + [Y[p - k:T - k] for k in range(1, p + 1)])
    return X, Y[p:]


def var_fit(Y, p):
    """OLS VAR(p) with constant. Returns (A list of p N x N matrices, Sigma residual covariance)."""
    Y = np.asarray(Y, float)
    N = Y.shape[1]
    X, Z = _lagged(Y, p)
    B = np.linalg.lstsq(X, Z, rcond=None)[0]                 # (1 + N p) x N
    U = Z - X @ B
    Sigma = U.T @ U / (len(Z) - X.shape[1])
    A = [B[1 + k * N:1 + (k + 1) * N].T for k in range(p)]   # A_k[i, j]: effect of j at lag k on i
    return A, Sigma


def select_lag(Y, pmax=5):
    """Lag order by BIC, all candidates fitted on the same sample."""
    Y = np.asarray(Y, float)
    N, best = Y.shape[1], None
    for p in range(1, pmax + 1):
        X, Z = _lagged(Y[pmax - p:], p)
        U = Z - X @ np.linalg.lstsq(X, Z, rcond=None)[0]
        T = len(Z)
        bic = np.linalg.slogdet(U.T @ U / T)[1] + np.log(T) / T * p * N * N
        if best is None or bic < best[0]:
            best = (bic, p)
    return best[1]


# ---------- variance decompositions ----------

def ma_coefs(A, H):
    """Moving-average matrices Psi_0..Psi_{H-1}: Psi_h = sum_k A_k Psi_{h-k}, Psi_0 = I."""
    N = A[0].shape[0]
    Psi = [np.eye(N)]
    for h in range(1, H):
        Psi.append(sum(A[k] @ Psi[h - 1 - k] for k in range(min(h, len(A)))))
    return Psi


def gfevd(A, Sigma, H=10):
    """Generalized FEVD, rows normalized to sum to 1 (Diebold & Yilmaz 2012, eq. 2-3).
    Unlike a Cholesky decomposition it does not depend on the order of the variables."""
    Psi = ma_coefs(A, H)
    num = sum((P @ Sigma) ** 2 for P in Psi) / np.diag(Sigma)[None, :]
    den = sum(np.diag(P @ Sigma @ P.T) for P in Psi)[:, None]
    theta = num / den
    return theta / theta.sum(1, keepdims=True)


def cholesky_fevd(A, Sigma, H=10):
    """Orthogonalized FEVD (order-dependent). Used as a cross-check: equals gfevd when Sigma is diagonal."""
    L = np.linalg.cholesky(Sigma)
    Psi = ma_coefs(A, H)
    num = sum((P @ L) ** 2 for P in Psi)
    return num / num.sum(1, keepdims=True)


# ---------- connectedness ----------

def connectedness(theta, names=None):
    """Diebold-Yilmaz measures in percent. from_[i]: share of i's variance from others;
    to[j]: j's contribution to all others; net = to - from; pairwise[i, j] = theta[j, i] - theta[i, j]
    (positive: i transmits to j on net)."""
    N = theta.shape[0]
    off = theta - np.diag(np.diag(theta))
    from_ = off.sum(1) * 100
    to = off.sum(0) * 100
    return dict(names=names or [str(i) for i in range(N)], total=float(off.sum() / N * 100),
                from_=from_, to=to, net=to - from_, pairwise=(off.T - off) * 100, theta=theta)


def spillover(Y, p=None, H=10, names=None):
    """Full pipeline on a T x N array of stationary series (returns or log volatilities)."""
    Y = np.asarray(Y, float)
    p = p or select_lag(Y)
    A, Sigma = var_fit(Y, p)
    out = connectedness(gfevd(A, Sigma, H), names)
    out["lag"] = p
    return out


def rolling_total(Y, window=200, H=10, p=2, step=1):
    """Total connectedness on rolling windows. Value at index t uses rows t-window+1..t only.
    Returns (end indices, total %, net % per variable)."""
    Y = np.asarray(Y, float)
    ends = np.arange(window - 1, len(Y), step)
    tot, net = np.empty(len(ends)), np.empty((len(ends), Y.shape[1]))
    for k, t in enumerate(ends):
        c = spillover(Y[t - window + 1:t + 1], p=p, H=H)
        tot[k], net[k] = c["total"], c["net"]
    return ends, tot, net


def simulate_var(A, Sigma, T, seed=0, burn=500):
    """Simulate a zero-mean VAR with Gaussian shocks of covariance Sigma."""
    rng = np.random.default_rng(seed)
    N, p = Sigma.shape[0], len(A)
    L = np.linalg.cholesky(Sigma)
    Y = np.zeros((T + burn, N))
    for t in range(p, T + burn):
        Y[t] = sum(A[k] @ Y[t - 1 - k] for k in range(p)) + L @ rng.standard_normal(N)
    return Y[burn:]
