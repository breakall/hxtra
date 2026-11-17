"""Actual microlooper_gesture.s in Unicorn; no footswitch hook is installed yet."""
import pytest

CODE, STATE = 0x28e60000, 0x28600000
HOLD_US = 400_000
TAP, OVERDUB = 1, 2


class Gesture:
    def __init__(self, m4emu, at=CODE):
        code, self.sym = m4emu.assemble('src/m4/microlooper_gesture.s', [], {})
        self.m = m4emu.M4(code, at)
        self.at = at

    def update(self, pressed, now, playing=False, state=STATE):
        return self.m.call(self.at + self.sym['microlooper_gesture_update'], state,
                           int(pressed), now & 0xffffffff, int(playing))

    def reset(self, state=STATE):
        return self.m.call(self.at + self.sym['microlooper_gesture_reset'], state)


def test_tap_is_only_emitted_on_release_and_requests_either_transport_transition(m4emu):
    g = Gesture(m4emu)
    for playing in (False, True):
        assert g.update(False, 0, playing) == 0
        assert g.update(True, 100, playing) == 0
        assert g.update(True, 110, playing) == 0
        assert g.update(False, 120, playing) == TAP
        assert g.update(False, 120, playing) == 0
        assert g.update(False, 130, playing) == 0


@pytest.mark.parametrize('duration', [1, HOLD_US - 1, HOLD_US, HOLD_US + 1, 2_000_000])
@pytest.mark.parametrize('start', [0, 0xffff_ff00])
def test_release_alone_distinguishes_tap_and_hold_even_across_clock_wrap(m4emu, duration, start):
    g = Gesture(m4emu)
    assert g.update(True, start, True) == 0
    assert g.update(False, start + duration, True) == (TAP if duration < HOLD_US else 0)
    assert g.update(False, start + duration + 1, True) == 0


def test_overdub_begins_at_400ms_and_ends_on_release_without_a_tap(m4emu):
    g = Gesture(m4emu)
    assert g.update(True, 17, True) == 0
    assert g.update(True, 17 + HOLD_US - 1, True) == 0
    assert g.update(True, 17 + HOLD_US, True) == OVERDUB
    assert g.update(True, 17 + HOLD_US, True) == OVERDUB
    assert g.update(True, 17 + HOLD_US + 1, True) == OVERDUB
    assert g.update(False, 17 + HOLD_US + 2, True) == 0
    assert g.update(False, 17 + HOLD_US + 3, True) == 0


def test_listening_hold_never_overdubs_or_captures_on_release(m4emu):
    g = Gesture(m4emu)
    assert g.update(True, 10) == 0
    assert g.update(True, 10 + HOLD_US) == 0
    assert g.update(True, 10 + 3 * HOLD_US) == 0
    assert g.update(False, 11 + 3 * HOLD_US) == 0
    assert g.update(True, 12 + 3 * HOLD_US) == 0
    assert g.update(False, 13 + 3 * HOLD_US) == TAP


def test_current_playback_state_gates_an_already_recognized_hold(m4emu):
    g = Gesture(m4emu)
    assert g.update(True, 0, True) == 0
    assert g.update(True, HOLD_US, True) == OVERDUB
    assert g.update(True, HOLD_US + 1, False) == 0
    assert g.update(True, HOLD_US + 2, True) == OVERDUB
    assert g.update(False, HOLD_US + 3, True) == 0


def test_recognized_hold_stays_latched_across_a_full_clock_period(m4emu):
    g = Gesture(m4emu)
    assert g.update(True, 0xffff_ff00, True) == 0
    assert g.update(True, 0xffff_ff00 + HOLD_US, True) == OVERDUB
    assert g.update(True, 0xffff_ff00, True) == OVERDUB
    assert g.update(False, 0xffff_ff01, True) == 0


def test_reset_cancels_pending_gesture_without_synthesizing_a_tap(m4emu):
    g = Gesture(m4emu)
    g.m.write(STATE - 4, b'LEFT' + b'\xff' * 8 + b'RGHT')
    assert g.reset() == 0
    assert g.m.read(STATE - 4, 16) == b'LEFT' + bytes(8) + b'RGHT'
    assert g.update(True, 0, True) == 0
    assert g.reset() == 0
    assert g.update(False, 1, True) == 0
    assert g.update(True, 2, True) == 0
    assert g.update(True, 2 + HOLD_US, True) == OVERDUB
    assert g.reset() == 0
    assert g.update(False, 3 + HOLD_US, True) == 0


def test_two_assignments_have_independent_state_and_no_adjacent_writes(m4emu):
    g = Gesture(m4emu)
    other = STATE + 12
    g.m.write(STATE - 4, b'LEFT' + bytes(8) + b'MIDL' + bytes(8) + b'RGHT')
    assert g.update(True, 0, True) == 0
    assert g.update(True, HOLD_US - 10, True, other) == 0
    assert g.update(True, HOLD_US, True) == OVERDUB
    assert g.update(False, HOLD_US + 1, True, other) == TAP
    assert g.update(True, HOLD_US + 2, True) == OVERDUB
    assert g.update(False, HOLD_US + 3, True) == 0
    assert g.m.read(STATE - 4, 4) == b'LEFT'
    assert g.m.read(STATE + 8, 4) == b'MIDL'
    assert g.m.read(other + 8, 4) == b'RGHT'


def test_routine_is_position_independent_and_accepts_nonzero_boolean_levels(m4emu):
    g = Gesture(m4emu, at=CODE + 0x1000)
    assert g.update(7, 0, 23) == 0
    assert g.update(7, HOLD_US, 23) == OVERDUB
    assert g.update(0, HOLD_US + 1, 23) == 0
