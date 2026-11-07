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

ALERT_SPACING_MIN = 6
STOP_MODES = ("STOPPED", "LOCKED_OUT")
EVENT_CLASSES = ("MACHINE", "SENSOR")
FAULT_TYPES = (
    "BEARING_WEAR", "SUCTION_STRAINER_CLOGGING", "CAVITATION",
    "DISCHARGE_RESTRICTION", "MISALIGNMENT", "IMBALANCE", "IMPELLER_WEAR",
    "AIR_ENTRAINMENT", "SENSOR_DRIFT", "SENSOR_STUCK", "SENSOR_CALIBRATION_SHIFT",
    "SENSOR_NOISE_SPIKES", "COMMUNICATION_LOSS", "UNKNOWN",
)

# Coupled-channel stillness: published diagnose uses k / 3.
COUPLED_STILL_FRACTION = 1 / 3
# In a closed loop these actuators react to the measurement, so they are not
# independent witnesses of a process-variable deviation (owner decision, fix 2).
ACTUATOR_CHANNELS = ("n", "vp")
ACCELEROMETER_CHANNELS = ("v", "a", "c")  # simulator: one accelerometer source
WIRELESS_CHANNELS = ("v", "a", "c", "bt")  # TECHNICAL_MODEL instrumentation
# TECHNICAL_MODEL §6 / plant.py: max winding tau=2400 s, bearing tau<=1500 s.
# Three time constants leave ~5% thermal settling error (hypothesis, not train fit).
THERMAL_SETTLE_MIN = 3 * 2400 // 60
# Oracle section 3: physical-value blocks 10-30 min; brief requires <=B1_PERSIST.
SHAPE_BLOCK_MIN = 10
RAMP_MIN_HOURS = 2
SHAPE_MIN_OBSERVATIONS = 3  # real updates, including 300 s wireless samples
# Conservative shape separation hypotheses, in physical units using B1 noise floors.
SHAPE_MIN_CHANGE_FLOORS = 3
SHAPE_FIT_FRACTION = 0.25  # max single block jump versus fitted ramp displacement
STEP_STABILITY_FRACTION = 0.25  # post-step MAD versus level change
RAMP_MIN_R2 = 0.8
NOISE_RECENT_MIN = 10  # persistence, rather than an isolated last-minute spike
NOISE_MIN_DENSE_COUNT = 30  # simulator: wireless std is not meaningful
