"""Native NAM-capacity admission for an explicitly compiled profile.

The caller supplies the compiled NAM profile's capacity and relocated model
name index. This module advertises no independently enabled feature.
"""

BUDGET = 0x28dfae0c
BUDGET_STOCK = bytes.fromhex('2de9 f041')
BUDGET_CALLS = (0x28dfffc4, 0x28e0060a)
TOTAL = 0x28dfa31c
TOTAL_STOCK = bytes.fromhex('90f8 c42a')
OBJECT_BASE, OBJECT_STRIDE, OBJECT_COUNT = 0xaf0, 0x9f4, 9
MODULE = 'src/m4/nam_capacity.s'


def asm_include(capacity, nam_name_index):
    """Explicit profile/name constants for src/m4/nam_capacity.s.

    Values describe the built image, not a user-selected runtime instance cap.
    The static model-table name index must come from that image's NAM model.
    """
    if type(capacity) is not int or capacity not in (1, 2, 3):
        raise ValueError('NAM profile capacity must be 1, 2 or 3')
    if type(nam_name_index) is not int or not 0 <= nam_name_index <= 0xffffffff:
        raise ValueError('NAM name index must be an unsigned 32-bit integer')
    return (f'.equ NC_CAPACITY, {capacity}\n'
            f'.equ NC_NAM_NAME_INDEX, {nam_name_index:#x}\n'
            f'.equ NC_NATIVE_BUDGET, {BUDGET | 1:#x}\n')


def install(p, capacity, nam_name_index):
    """Replace the two guarded native admission calls, retaining their ABI.

    This is a direct call replacement: a generic shared chain would hide the
    fifth stack argument behind its own saved-register frame.
    """
    import patch_menu
    include = asm_include(capacity, nam_name_index)
    if MODULE in p.modules:
        raise SystemExit('NAM capacity admission is already installed')
    p.expect(BUDGET, BUDGET_STOCK, 'native candidate DSP budget')
    p.expect(TOTAL, TOTAL_STOCK, 'native preset cost total')
    for address in BUDGET_CALLS:
        p.expect(address, patch_menu.bl(address, BUDGET), 'native candidate budget call')
    module = p.module(MODULE, inc={'nam_capacity.inc': include})
    for address in BUDGET_CALLS:
        p.put(address, patch_menu.bl(address, module['nam_capacity_admit']), 'NAM profile admission')
    return module


def verify_installed(e0, capacity, nam_name_index):
    """Check exact compiled capacity/name code and both final call targets."""
    from pathlib import Path
    import tempfile
    import m4asm
    import kit_patch_amp as kit
    import patch_menu
    source = Path(__file__).resolve().parents[1] / MODULE
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, 'nam_capacity.inc').write_text(asm_include(capacity, nam_name_index))
        code, symbols = m4asm.assemble_module(str(source), include=(directory, str(source.parent)))
    segments = kit._parse_e0_segments(e0)
    def read(address, length=4):
        offset = kit._e0_vaddr_to_foff(segments, address, length)
        return e0[offset:offset+length]
    if read(BUDGET) != BUDGET_STOCK or read(TOTAL) != TOTAL_STOCK:
        raise ValueError('native NAM budget/total entry is changed')
    matches = []
    cursor = 0
    while True:
        offset = e0.find(code, cursor)
        if offset < 0:
            break
        cursor = offset+1
        for _, start, size, address, _ in segments:
            if start <= offset and offset+len(code) <= start+size:
                entry = address+offset-start+symbols['nam_capacity_admit']
                if all(read(site) == patch_menu.bl(site, entry) for site in BUDGET_CALLS):
                    matches.append(entry)
    if len(matches) != 1:
        raise ValueError('compiled NAM capacity or native admission calls are not installed')
    return dict(nam_capacity=capacity, nam_name_index=nam_name_index, nam_capacity_entry=matches[0])
