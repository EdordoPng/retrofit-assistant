"""Published B1 parameters and causal estimator constants."""

B1_K = 6.0
B1_PERSIST = 15
BASELINE_HOURS = 24
MIN_POOL_SAMPLES = 30
MIN_REGIME_SAMPLES = 1
MAD_SCALE = 1.4826
GAP_MIN_ROWS = 30
FLAT_MIN_COUNT = 30
Z_FLOORS = {
    "v": 0.05, "a": 0.01, "c": 0.05, "bt": 0.3,
    "ps": 1.0, "pd": 2.0, "i": 0.3, "pw": 0.2, "q": 2.0,
    "n": 5.0, "wt": 0.5, "tf": 0.3, "vp": 0.5,
}
ZS_FLOOR_ABS = 1e-3
ZS_FLOOR_REL = 0.05
