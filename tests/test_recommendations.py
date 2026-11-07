import itertools

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.baselines import CH

from retrofit_assistant.params import EVENT_CLASSES, FAULT_TYPES
from retrofit_assistant.recommendations import DECIDED_BY, recommend


def frame(rows):
    return pd.DataFrame(rows, columns=["event_class", "fault_type", "evidence", "recommended_action", "decided_by"])


def test_all_combinations_and_sensor_order():
    alerts = frame([(cls, fault, "no channel", "old", reason)
                    for cls, fault, reason in itertools.product(EVENT_CLASSES, FAULT_TYPES, DECIDED_BY)])
    actions = recommend(alerts).recommended_action
    for row, action in zip(alerts.itertuples(), actions):
        assert action.startswith("Inspect: ")
        assert ". Do: " in action and ". Rule out first: " in action and action.endswith(".")
        assert not any(word in action.lower() for word in ("automatically", "set to", "setpoint"))
        if row.event_class == "SENSOR" and row.fault_type != "COMMUNICATION_LOSS":
            assert "verify the instrument" in action
            assert "independent measurement or calibration check before opening the pump" in action
        if row.event_class == "SENSOR" and row.fault_type == "COMMUNICATION_LOSS":
            assert "check gateway, network and instrument power, and confirm that data returns before any work on the pump" in action
            assert "calibration" not in action


def test_process_unknown_and_channel_boundaries():
    alerts = frame([("MACHINE", "UNKNOWN", "fluid_temp_c high", "old", "official"),
                    ("SENSOR", "UNKNOWN", "no signal", "old", "official"),
                    ("MACHINE", "UNKNOWN", "xfluid_temp_c_extra", "old", "official")])
    actions = recommend(alerts).recommended_action.tolist()
    assert "fluid_temp_c" in actions[0] and "inlet water temperature" in actions[0]
    assert all(term in actions[0] for term in ("load", "suction level", "valve position", "instrument"))
    assert "fluid_temp_c" not in actions[2]
    labels = ("vibration velocity", "vibration acceleration", "vibration crest factor",
              "bearing temperature", "suction pressure", "discharge pressure",
              "motor current", "motor power", "flow", "motor speed",
              "motor winding temperature", "fluid temperature", "valve position")
    for channel, label in zip(CH.values(), labels, strict=True):
        row = frame([("MACHINE", "UNKNOWN", f"{channel}=1", "old", "official")])
        assert f"{label} ({channel})" in recommend(row).recommended_action.iloc[0]
    row = frame([("MACHINE", "UNKNOWN", "flow_m3_h then fluid_temp_c", "old", "official")])
    assert "flow_m3_h" in recommend(row).recommended_action.iloc[0]
    assert "fluid_temp_c" not in recommend(row).recommended_action.iloc[0]


def test_preservation_determinism_and_row_independence():
    alerts = frame([("MACHINE", "UNKNOWN", "fluid_temp_c", "old", "official"),
                    ("SENSOR", "SENSOR_STUCK", "bearing_temp_c", "old", "source_stuck")])
    alerts.index = pd.Index([7, 7], name="original")
    alerts["extra"] = pd.Series([1, 2], index=alerts.index, dtype="int16")
    before = alerts.copy(deep=True)
    result = recommend(alerts)
    assert_frame_equal(alerts, before)
    assert_frame_equal(result.drop(columns="recommended_action"), alerts.drop(columns="recommended_action"))
    assert list(result.columns) == list(alerts.columns)
    assert_frame_equal(result, recommend(alerts))
    assert recommend(alerts.iloc[::-1]).recommended_action.tolist() == result.recommended_action.tolist()[::-1]


def test_provenance_messages():
    alerts = frame([("MACHINE", "UNKNOWN", "no channel", "old", reason) for reason in DECIDED_BY])
    actions = dict(zip(DECIDED_BY, recommend(alerts).recommended_action))
    assert actions["official"].endswith("Note: the class was not verified with independent witnesses.")
    assert "a process cause before a mechanical one (an independent witness follows the deviation)" in actions["rediagnose_refuted"]
    assert "accelerometer mounting" in actions["rediagnose_accelerometer"]
    assert actions["source_cavitation"].endswith("Note: the NPSH margin needs site verification.")
    for reason in DECIDED_BY:
        assert (" Note: " in actions[reason]) == (reason in ("official", "source_cavitation"))


def test_invalid_provenance_and_empty_frame():
    alerts = frame([])
    assert_frame_equal(recommend(alerts), alerts)
    with pytest.raises(ValueError):
        recommend(alerts.drop(columns="decided_by"))
    with pytest.raises(ValueError):
        recommend(frame([("SENSOR", "UNKNOWN", "", "", "invalid")]))
