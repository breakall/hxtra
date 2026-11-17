"""Encoded diagnostic publisher: staged frame writes and guarded source reads."""
import random

import pytest

import microlooper_adapter as adapter
import microlooper_publisher as publisher
import patch_comp
import sasm
import ssim

SIDECAR, FRAME = 0xe7000, 0xb4000


def accept(frame):
    if (frame[219], frame[221]) != (publisher.TAG, 16):
        return None
    if frame[220] & 1 or frame[220] != frame[238]:
        return None
    if frame[222] != adapter.MAGIC:
        return None
    return frame[222:238]


def run(sequence=2, magic=adapter.MAGIC, mutate_after=None):
    sim = ssim.Sim()
    sim.strict_cbufen = True
    sections, symbols = publisher.assemble(0xe5000, SIDECAR)
    sim.load(sections)
    rng = random.Random(714)
    for code in range(0x60):
        sim.set(code, rng.getrandbits(32))
    for r in range(16):
        sim.alt[r] = rng.getrandbits(32)
    sim.set(0x14, FRAME)
    sim.set(ssim.U_MODE1, 0x1600000)
    for code in (ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79):
        sim.set(code, rng.getrandbits(32))
    old = [adapter.MAGIC] + [0x12340000 + k for k in range(15)]
    new = [magic] + [0x76540000 + k for k in range(15)]
    for k in range(adapter.STATE_WORDS):
        sim.wr(SIDECAR + k, 0)
    for k, word in enumerate(new):
        sim.wr(SIDECAR + adapter.SNAPSHOT_OFFSET + k, word)
    sim.wr(SIDECAR + adapter.SOURCE_SEQUENCE_OFFSET, sequence)
    frame = [0xabcdef00 + k for k in range(256)]
    frame[219], frame[220], frame[221], frame[238] = publisher.TAG, 0xfffffffc, 16, 0xfffffffc
    frame[222:238] = old
    for k, word in enumerate(frame):
        sim.wr(FRAME + k, word)
    regs = list(range(0x60)) + [ssim.U_MODE1, ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79]
    before = [sim.get(k) for k in regs], list(sim.alt[:16])
    events, snapshots = [], []
    store = sim.wr

    def observe(address, word):
        store(address, word)
        if FRAME <= address < FRAME + 256:
            events.append((address - FRAME, word & 0xffffffff))
            if mutate_after is not None and address == FRAME + 222 + mutate_after:
                # A full new source publication while the old frame is copied.
                store(SIDECAR + 180, (sequence + 1) & 0xffffffff)
                for k in range(16):
                    store(SIDECAR + 160 + k, adapter.MAGIC if k == 0 else 0x99990000 + k)
                store(SIDECAR + 180, (sequence + 2) & 0xffffffff)
            snapshots.append([sim.rd(FRAME + k) for k in range(256)])
    sim.wr = observe
    sim.call(symbols['MICROLOOPER_PUBLISH_CONTEXT'], limit=256)
    assert before == ([sim.get(k) for k in regs], list(sim.alt[:16]))
    assert not sim.loops and not sim.pcstk
    after = [sim.rd(FRAME + k) for k in range(256)]
    assert all(frame[k] == after[k] for k in range(256) if not 219 <= k <= 238)
    return sim, frame, old, new, events, snapshots


@pytest.mark.parametrize('sequence', [0, 2, 0xfffffffe])
def test_valid_record_stages_both_guards_before_payload_and_publishes_begin_last(sequence):
    sim, original, old, new, events, snapshots = run(sequence)
    assert events[:2] == [(220, sequence | 1), (238, sequence | 1)]
    assert events[-2:] == [(238, sequence), (220, sequence)]
    assert accept(snapshots[-1]) == new
    assert all(accept(frame) is None for frame in snapshots[:-1])
    assert [sim.rd(SIDECAR + 160 + k) for k in range(16)] == new
    assert sim.rd(SIDECAR + 180) == sequence


@pytest.mark.parametrize('sequence,magic', [(1, adapter.MAGIC), (0xffffffff, adapter.MAGIC),
                                            (0, 0), (2, 0x12345678)])
def test_odd_or_missing_source_invalidates_destination_without_copying(sequence, magic):
    _, original, _, _, events, snapshots = run(sequence, magic)
    assert [offset for offset, _ in events] == [220, 238]
    assert snapshots[-1][222:238] == original[222:238]
    assert accept(snapshots[-1]) is None


@pytest.mark.parametrize('mutate_after', range(16))
def test_source_changed_at_each_payload_store_abandons_without_retry(mutate_after):
    _, _, _, _, events, snapshots = run(mutate_after=mutate_after)
    assert len(events) == 20  # two invalidations, tag/count, sixteen payload stores; no commit/retry
    assert all(accept(frame) is None for frame in snapshots)
    assert snapshots[-1][220] & 1 and snapshots[-1][238] & 1


def test_reader_interleavings_never_accept_a_mixed_payload():
    _, old_frame, old, new, events, _ = run()
    # Model a receiver copying one word at a time while the actual encoded
    # producer advances through every possible cut of its store trace. Read
    # before/after guards exactly as the M4 consumer must; no cached begin-only check.
    for cut in range(len(events) + 1):
        for split in range(17):
            frame = old_frame.copy()
            for offset, value in events[:cut]:
                frame[offset] = value
            begin = frame[220]
            end = frame[238]
            captured = frame[222:222 + split]
            for offset, value in events[cut:]:
                frame[offset] = value
            captured += frame[222 + split:238]
            valid = not begin & 1 and begin == end == frame[220] == frame[238]
            if valid:
                assert captured in (old, new)


def test_gr_variant_retains_every_address_and_native_field_store():
    dm, pm, entry = 0xe4850, 0xe5000, 0xe5400
    original = patch_comp.dsp_asm(dm, pm)
    variant = publisher.dsp_source(dm, pm, entry)
    old_sections, old_symbols = sasm.assemble(original, 'old_frame_probe.asm')
    new_sections, new_symbols = publisher.assemble_gr(dm, pm, entry)
    assert old_symbols == new_symbols
    assert [(s.kind, s.addr, len(s.words)) for s in old_sections] == [
        (s.kind, s.addr, len(s.words)) for s in new_sections]
    old_pm = next(s.words for s in old_sections if s.kind == 'pm')
    new_pm = next(s.words for s in new_sections if s.kind == 'pm')
    changed = [k for k, (a, b) in enumerate(zip(old_pm, new_pm)) if a != b]
    assert changed == list(range(changed[0], changed[0] + publisher.REPLACED_INSTRUCTIONS))
    for field in (200, 216, 217, 218, 250, 251, 252):
        assert variant.count(f'DM({field}, I4) =') == original.count(f'DM({field}, I4) =')
    assert 'CALL 0xe5400;' in variant
    assert variant.count('      NOP;') == 61


@pytest.mark.parametrize('base,sidecar', [(1, SIDECAR), (0xe5000, SIDECAR+1), (0xe5000, 0xfffff)])
def test_explicit_publisher_placement_validation(base, sidecar):
    with pytest.raises(ValueError):
        publisher.assemble(base, sidecar)


def test_actual_gr_process_runs_publisher_without_changing_audio_or_meter_transport():
    # Reuse the existing encoded GR wrapper/core fixture. Patch only the proven
    # 62-instruction export slot, leaving its synthetic native core/control
    # callees and all original process/control entry addresses intact.
    from test_gr import probe, knobs, block, OUT, IN1
    from test_gr import FRAME as GR_FRAME
    ordinary, ordinary_symbols = probe()
    diagnostic, symbols = probe()
    old_sections, _ = sasm.assemble(patch_comp.dsp_asm(0xe4850, 0xc4ef8), 'old.asm')
    new_sections, _ = publisher.assemble_gr(0xe4850, 0xc4ef8, 0xe5000)
    old = next(s for s in old_sections if s.kind == 'pm')
    new = next(s for s in new_sections if s.kind == 'pm')
    for offset, (a, b) in enumerate(zip(old.words, new.words)):
        if a != b:
            diagnostic.pm[old.addr + offset] = b
    code, _ = publisher.assemble(0xe5000, SIDECAR)
    diagnostic.load(code)
    payload = [adapter.MAGIC] + [0x45670000 + k for k in range(15)]
    for k, word in enumerate(payload):
        diagnostic.wr(SIDECAR + 160 + k, word)
    diagnostic.wr(SIDECAR + 180, 2)
    for sim, sym in ((ordinary, ordinary_symbols), (diagnostic, symbols)):
        knobs(sim, sym, 'CTRL_2719', 0x96000, 2, 1, 20)
        for k in range(64):
            block(sim, sym, 'ENTRY_2719', 0x96000, 0.8 if k == 40 else 0.5)
    for start, count in ((IN1, 16), (OUT, 16), (GR_FRAME, 200), (GR_FRAME + 250, 6)):
        assert [diagnostic.rd(start + k) for k in range(count)] == [ordinary.rd(start + k) for k in range(count)]
    assert [diagnostic.rd(GR_FRAME + k) for k in (200, 216, 217, 218)] == [
        ordinary.rd(GR_FRAME + k) for k in (200, 216, 217, 218)]
    assert accept([diagnostic.rd(GR_FRAME + k) for k in range(256)]) == payload
    regs = list(range(0x60)) + [ssim.U_MODE1, ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79]
    assert [diagnostic.get(k) for k in regs] == [ordinary.get(k) for k in regs]
