"""Staged NAM admission against actual HX Stomp pricing/budget/total code."""
import struct

import pytest

import nam_capacity as nc

CODE, PRESET, DESCRIPTOR, RESULT = 0x28e60000, 0x28600000, 0x28611000, 0x28612000
_code = {}


@pytest.mark.firmware
def test_installer_uses_actual_native_calls_and_profile_identity(m4emu, native_image):
    import patch_menu as pm
    from firmware import branch_target, stock_e0
    p = pm.Patch(stock_e0(), [], {})
    configured_name = native_image[3][0]
    module = nc.install(p, 1, configured_name)
    for address in nc.BUDGET_CALLS:
        assert branch_target(address, p.read(address, 4)) == module['nam_capacity_admit']
    budget = Budget(m4emu, native_image, 1)
    budget.m.load(p.cave.va, p.cave.buf)
    budget.entry = module['nam_capacity_admit']
    budget.block(0)
    budget.total()
    assert budget.check() == (0, 0)
    assert budget.check(nam=False) == (0, 1)
    assert nc.verify_installed(p.entry0(), 1, configured_name)['nam_capacity_entry'] == module['nam_capacity_admit']
    with pytest.raises(ValueError, match='not installed'):
        nc.verify_installed(p.entry0(), 2, configured_name)
    for address in (nc.BUDGET, nc.TOTAL):
        corrupted = bytearray(p.entry0())
        corrupted[p.off(address, 1)] ^= 1
        with pytest.raises(ValueError, match='budget/total entry'):
            nc.verify_installed(bytes(corrupted), 1, configured_name)
    with pytest.raises(SystemExit, match='already installed'):
        nc.install(p, 1, configured_name)


@pytest.fixture(scope='module')
def native_image():
    from firmware import reader, stock_e0
    read = reader(stock_e0())
    assert read(nc.BUDGET, 4) == nc.BUDGET_STOCK
    assert read(nc.TOTAL, 4) == nc.TOTAL_STOCK
    table, = struct.unpack('<I', read(0x28e01e80, 4))
    raw = read(table, 823 * 12)
    rows = list(struct.iter_unpack('<IHHI', raw))
    # Configure real stock names as NAM/other identities in this isolated test;
    # no fake pricing routine or production NAM metadata is substituted.
    choices = [row for row in rows if 0 < row[3] <= 500]
    return read, table, raw, choices[0], choices[1]


class Budget:
    def __init__(self, m4emu, image, capacity):
        import patch_menu as pm
        read, table, raw, nam, other = image
        self.nam, self.other = nam[0], other[0]
        self.nam_cost, self.other_cost = nam[3], other[3]
        key = capacity, self.nam
        if key not in _code:
            _code[key] = m4emu.assemble('src/m4/nam_capacity.s', [], {},
                                      inc={'nam_capacity.inc': nc.asm_include(*key)})
        code, symbols = _code[key]
        self.entry = CODE + symbols['nam_capacity_admit']
        self.m = m4emu.M4(code, CODE)
        self.m.load(nc.BUDGET, read(nc.BUDGET, 0x44))
        self.m.load(0x28e01d50, read(0x28e01d50, 0x146))
        self.m.load(nc.TOTAL, read(nc.TOTAL, 0x118))
        self.m.load(0x28e01b1c, read(0x28e01b1c, 0xf0))
        self.m.write(table, raw)
        # Stock stores rows unsorted in the image; its own recursive table
        # sorter initializes the runtime table that the binary search expects.
        self.m.call(0x28e01b1c, 0, 822)
        for site in nc.BUDGET_CALLS:
            assert read(site, 4) == pm.bl(site, nc.BUDGET)
        self.m.u8(PRESET + 0xac4, 5)
        self.m.u32(PRESET + 0xa88, 1500)

    def block(self, index, *, nam=True, active=True, flags=None, cost=None):
        at = PRESET + nc.OBJECT_BASE + nc.OBJECT_STRIDE * index
        self.m.u32(at + 0x24, int(active) if flags is None else flags)
        self.m.u32(at + 0x54, self.nam if nam else self.other)
        self.m.u32(at + 0x44, (self.nam_cost if nam else self.other_cost) if cost is None else cost)
        return at

    def total(self):
        assert self.m.call(nc.TOTAL, PRESET) == 0
        return self.m.u32(PRESET + 0xa88)

    def check(self, *, nam=True, replaced=0, kind=6, name=None, native=False):
        self.m.write(DESCRIPTOR, struct.pack('<3I', kind, (self.nam if nam else self.other) if name is None else name, 0))
        self.m.write(RESULT - 4, b'LEFT\xccRGHT')
        self.m.u32(0x28f00000, RESULT)  # fifth ABI argument, before either frame
        before = self.m.read(PRESET, 0x6484)
        status = self.m.call(nc.BUDGET if native else self.entry, 0, PRESET, replaced, DESCRIPTOR)
        assert self.m.read(PRESET, 0x6484) == before
        assert self.m.read(RESULT - 4, 4) == b'LEFT'
        assert self.m.read(RESULT + 1, 4) == b'RGHT'
        return status, self.m.read(RESULT, 1)[0]


@pytest.mark.firmware
@pytest.mark.parametrize('capacity', [1, 2, 3])
@pytest.mark.parametrize('existing', [0, 1, 2, 3])
def test_capacity_boundary_uses_standard_false_only_after_native_accepts(m4emu, native_image, capacity, existing):
    b = Budget(m4emu, native_image, capacity)
    for i in range(existing):
        b.block(i)
    b.total()
    assert b.check(native=True) == (0, 1)
    assert b.check() == (0, int(existing < capacity))
    assert b.check(nam=False) == b.check(nam=False, native=True) == (0, 1)


@pytest.mark.firmware
@pytest.mark.parametrize('capacity', [1, 2, 3])
def test_replacing_same_nam_refunds_its_counted_pool_slot(m4emu, native_image, capacity):
    b = Budget(m4emu, native_image, capacity)
    blocks = [b.block(i) for i in range(capacity)]
    b.total()
    assert b.check() == (0, 0)
    assert b.check(replaced=blocks[-1]) == (0, 1)
    assert b.check(nam=False, replaced=blocks[-1]) == b.check(nam=False, replaced=blocks[-1], native=True) == (0, 1)


@pytest.mark.firmware
@pytest.mark.parametrize('capacity', [1, 2, 3])
def test_replacing_non_nam_does_not_refund_nam_but_removal_frees_capacity(m4emu, native_image, capacity):
    b = Budget(m4emu, native_image, capacity)
    for i in range(capacity):
        b.block(i)
    other = b.block(4, nam=False)
    b.total()
    assert b.check(replaced=other) == (0, 0)
    b.block(capacity - 1, active=False)
    b.total()
    assert b.check(replaced=other) == (0, 1)


@pytest.mark.firmware
@pytest.mark.parametrize('limit', [0, 1, 2, 3, 4, 5, 255])
@pytest.mark.parametrize('selected', range(9))
def test_object_eligibility_matches_actual_native_total(m4emu, native_image, limit, selected):
    b = Budget(m4emu, native_image, 1)
    b.m.u8(PRESET + 0xac4, limit)
    eligible = [i for i in range(9) if i >= 5 or i < min(limit, 5)]
    for i in range(9):
        b.block(i, nam=i == selected, cost=1 << i)
    assert b.total() == 1500 + sum(1 << i for i in eligible)
    assert b.check(native=True) == (0, 1)
    assert b.check() == (0, int(selected not in eligible))


@pytest.mark.firmware
@pytest.mark.parametrize('flags', [0, 2, 0x80000000])
def test_inactive_nam_does_not_consume_or_refund_a_slot(m4emu, native_image, flags):
    b = Budget(m4emu, native_image, 1)
    b.block(0)
    inactive = b.block(1, flags=flags)
    b.total()
    assert b.check(replaced=inactive) == (0, 0)


@pytest.mark.firmware
def test_excluded_replacement_does_not_refund_a_counted_nam(m4emu, native_image):
    b = Budget(m4emu, native_image, 1)
    b.m.u8(PRESET + 0xac4, 1)
    b.block(0)
    excluded = b.block(4)
    b.total()
    assert b.check(replaced=excluded) == (0, 0)


@pytest.mark.firmware
@pytest.mark.parametrize('kind,name', [(34, None), (6, 0xffffffff)])
def test_original_pricing_error_and_output_semantics_are_unchanged(m4emu, native_image, kind, name):
    b = Budget(m4emu, native_image, 1)
    b.block(0)
    b.total()
    expected = b.check(kind=kind, name=name, native=True)
    assert expected[0] & 0x80000000
    assert b.check(kind=kind, name=name) == expected


@pytest.mark.firmware
def test_native_dsp_refusal_cannot_be_overridden_and_removal_is_not_a_candidate(m4emu, native_image):
    b = Budget(m4emu, native_image, 3)
    b.m.u32(PRESET + 0xa88, 9000)
    assert b.check(native=True) == b.check() == (0, 0)
    b = Budget(m4emu, native_image, 1)
    replaced = b.block(0)
    b.total()
    assert b.check(kind=0, replaced=replaced, native=True) == b.check(kind=0, replaced=replaced) == (0, 1)


@pytest.mark.parametrize('capacity', [0, 4, -1, True, 1.0])
def test_profile_capacity_must_be_explicit_and_supported(capacity):
    with pytest.raises(ValueError, match='profile capacity'):
        nc.asm_include(capacity, 1)


@pytest.mark.parametrize('name', [-1, 0x100000000, True, 1.0])
def test_name_index_must_be_an_actual_unsigned_index(name):
    with pytest.raises(ValueError, match='name index'):
        nc.asm_include(1, name)


def test_adapter_is_not_a_discoverable_feature():
    import features
    assert 'nam_capacity' not in {features.name(m) for m in features.load()}
    assert not hasattr(nc, 'FLAG') and not hasattr(nc, 'apply')
