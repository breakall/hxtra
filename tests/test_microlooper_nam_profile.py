"""A real single-slot NAM check for the micro-looper code-space profile."""
import hashlib

import pytest

import nam_multi as nm


@pytest.mark.parametrize('mid,slots,digest', [
    (False, 2, 'bdaf3ecf1bb9956865fa646777619fa97c37b77f4464e2c25f3e5d2d03a17984'),
    (False, 3, '811753a4c725e22952de762ea7ef742fe2d28d203150a08dea3d66848d8efde6'),
    (True, 2, '2485553bfa4281da940d8144cf686570d4931fa2cf3c43a5d42d36456ef46b08'),
    (True, 3, '4f34755dd7abe8d0e40cc72ee0a9beefca80b580427ea7c50943b1f9077cde48'),
])
def test_existing_profiles_generate_identical_assembly(mid, slots, digest):
    with nm.flags(['--mid-sweep'] if mid else []):
        asm, _ = nm.build(slots)
    assert hashlib.sha256(asm.encode()).hexdigest() == digest


def test_single_slot_reserves_real_model_and_ring_memory_without_overlap():
    with nm.flags(['--mid-sweep']):
        asm, lay = nm.build(1)
        assert lay.slots == 1 and len(lay.slot) == 1
        assert lay.v['NSLOTS'] == 1
        assert lay.b3_to <= lay.cold_nw
        assert lay.sdram_words() >= lay.sdr_need
        assert lay.cold_nw - lay.b3_to > 4000
        assert 'NSLOTS' in asm


@pytest.mark.slow
def test_single_slot_encoded_kernel_reference_lifecycle_and_dma(weights):
    with nm.flags(['--mid-sweep']):
        asm, lay = nm.build(1, backoff=3)
        ok, result, suite = nm.check(asm, lay, weights, nblk=4)
    assert ok, result
    assert isinstance(suite, nm.SingleKernelCheck)
    assert result['timeout'] is not None
    assert result['worst'] <= 36000
    assert any('overflow' in name for name, _ in suite.rig.cycles)
    assert any('replaces removed' in name for name, _ in suite.rig.cycles)
    assert any('capture replaced' in name for name, _ in suite.rig.cycles)
