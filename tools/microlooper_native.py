"""Explicit native M4 installation for the development Atmosphere build.

The explicit installer composes native graph lifetimes, route discovery,
eligibility, the shared key owner, periodic polling, bool writes and selective
filters. It is tested offline with stock functions and ROM mutex bodies.
The development feature owns build selection; hardware qualification remains
separate. This module itself supplies no automatic FLAG/apply entry point.
"""
import hashlib
import struct
from microlooper_definition import EFFECT, MODELS

PRESET_ID = EFFECT.preset_id
PLAY_SLOT = next(p.slot for p in EFFECT.parameters if p.name == 'Play')
OVERDUB_SLOT = next(p.slot for p in EFFECT.parameters if p.name == 'Overdub')
STATE_BYTES = 32
ROUTE_BYTES = 20  # state*, binding*, switch_index, stock_handler, lp_event_handler
BYPASS_FILTER_SITE = 0x28dd11aa
BYPASS_FILTER_STOCK = bytes.fromhex('9df8 2830')
TICK_LITERAL, TICK_STOCK = 0x28dd2944, 0x28dd1015
PARAMETER_FILTER_SITE = 0x28e04864
PARAMETER_FILTER_STOCK = bytes.fromhex('2de9 f043')
NATIVE_INTEGRATION_VERIFIED = False  # hardware qualification remains separate

MODULE = 'src/m4/microlooper.s'
MANIFEST_MAGIC = b'HXTRA_MLCTRLv4\0\0'
MANIFEST_HEADER = struct.Struct('<16s13I32s')
# Version4's position-independent bytes and public entry offsets. Source tests
# force an explicit manifest revision whenever the installed runtime changes.
MODULE_SHA256 = '8e63de2a6020fb03e6917c21cac9cdfddfb2017543633e2edc25418f0571a249'
LAYOUT = {
    'microlooper_native_bypass_filter': 624,
    'microlooper_native_parameter_filter': 664,
    'microlooper_controller_key': 1792,
    'microlooper_controller_tick': 1930,
    'microlooper_controller_object_before': 1968,
    'microlooper_controller_model_before': 2006,
    'microlooper_controller_up_before': 2010,
    'microlooper_controller_down_before': 2014,
    'microlooper_controller_range_before': 2016,
    'microlooper_controller_lower_bypass_before': 2078,
    'microlooper_controller_bypass_before': 2106,
    'microlooper_controller_after': 2168,
}
HANDLER, HANDLER_STOCK = 0x28dd1978, bytes.fromhex('2de9 f043')
# No stack-argument entry is chained. Native primitive creation/destruction and
# retained-instance moves supply independent ownership invalidation boundaries.
LIFECYCLE = (
    (0x28dfc2c4, '2de9 f04f', 'microlooper_controller_object_before', 'block initialization'),
    (0x28df38d0, 'f0b5 d1f8 f059', 'microlooper_controller_object_before', 'block destruction'),
    (0x28e02d40, 'f0b5 99b0', 'microlooper_controller_model_before', 'model insertion/replacement'),
    (0x28e02ee0, 'f0b5 99b0', 'microlooper_controller_model_before', 'alternate model replacement'),
    (0x28e030bc, '2de9 f043', 'microlooper_controller_range_before', 'block move'),
    (0x28e03268, '2de9 f041', 'microlooper_controller_up_before', 'adjacent forward move'),
    (0x28e03380, '2de9 f041', 'microlooper_controller_down_before', 'adjacent backward move'),
    (0x28e03498, '2de9 f041', 'microlooper_controller_model_before', 'block removal'),
    (0x28e06b4c, '70b5 0b78', 'microlooper_controller_lower_bypass_before', 'UI/MIDI/snapshot bypass transition'),
)
CALLED = (
    (0x28d96084, '0048 7047 4c8b 1228', 'native assignment manager getter'),
    (0x28e07844, '20b9 044b 1868 0830', 'native graph mutex lock'),
    (0x28e0785c, '20b9 044b 1868 0830', 'native graph mutex unlock'),
    (0x28e0fe94, 'f0b5 0646', 'native model lookup'),
    (0x28e04514, 'f0b5 83b0', 'native bypass lookup'),
    (0x28e1f844, 'b0f5 bf7f', 'native setting getter'),
    (0x28da6458, '0120 fdf7 a7b9', 'microsecond clock'),
    (0x28e24c00, '5ff8 00f0 bd34 0010', 'native recursive mutex lock wrapper'),
    (0x28e24bb0, '5ff8 00f0 d134 0010', 'native recursive mutex unlock wrapper'),
    (0x10000500, 'f8b5 0746', 'native mutex acquisition'),
    (0x10000560, '7b68 0133 3046 7b60', 'native same-task recursion counter'),
)


def asm_include():
    """One native identity predicate generated from the declared model family.

    r0 and argument registers survive; only r12 and condition flags change.
    Z is set exactly for an Atmosphere model. Inline hooks preserve their LR.
    """
    lines = ['.thumb_func', 'microlooper_is_model:']
    for effect in MODELS:
        lines += [f'    movw r12, #{effect.preset_id}', '    cmp r0, r12',
                  '    beq .Lml_model_match']
    return '\n'.join(lines + ['.Lml_model_match:', '    bx lr', ''])


def install(p, *, shared_input_hook=None):
    """Install verified native controller seams through one shared input owner.

    shared_input_hook is the long-press owner's (Hook, original trampoline,
    lp_event) tuple. Without it this installer owns the untouched stock entry.
    No instance-count policy or resource admission is implemented here.
    """
    import patch_menu as pm
    if MODULE in p.modules:
        raise SystemExit('microlooper native controller is already installed')
    for address, stock, what in CALLED:
        if address == pm.GET_VALUE and address in p.owned:
            # The shared settings engine preserves the native getter ABI and
            # forwards ordinary ID21 through its guarded stock trampoline.
            engine = p.modules.get('src/m4/virtual_settings.s')
            getter = p.owned[address]
            if (engine is None or getter.owner != 'HXtra'
                    or getter.prologue != bytes.fromhex(stock)
                    or getter.handler != engine['virt_get']):
                raise SystemExit('microlooper requires the native or shared virtual-settings getter')
            continue
        p.expect(address, bytes.fromhex(stock), what)
    for address, stock, _, what in LIFECYCLE:
        p.expect(address, bytes.fromhex(stock), what)
    p.expect(BYPASS_FILTER_SITE, BYPASS_FILTER_STOCK, 'selective Atmosphere switch bypass')
    p.expect(PARAMETER_FILTER_SITE, PARAMETER_FILTER_STOCK, 'Atmosphere transport snapshot filter')
    if shared_input_hook is None:
        hook = p.own_entry(HANDLER, HANDLER_STOCK, 'Atmosphere footswitch event routing')
        stock, lp_event = hook.stock, 0
    else:
        hook, stock, lp_event = shared_input_hook
        if hook.fn != HANDLER or hook.handler is not None or stock != hook.stock:
            raise SystemExit('microlooper requires the unbound shared footswitch hook')
    m = p.module(MODULE, inc={'microlooper_models.inc': asm_include()})
    module_bytes = bytes(p.cave.buf[m.va - p.cave.va:])
    digest = hashlib.sha256(module_bytes).digest()
    if digest.hex() != MODULE_SHA256 or any(m.symbols[name] != offset for name, offset in LAYOUT.items()):
        raise SystemExit('microlooper controller source and versioned runtime manifest disagree')
    lifecycle_records = []
    for address, stock_bytes, before, what in LIFECYCLE:
        lifecycle = p.own_entry(address, bytes.fromhex(stock_bytes), what)
        kind = 1 if address == 0x28dfc2c4 else 2 if address == 0x28df38d0 else 0
        target = p.add(_lifecycle_veneer(p.next(), lifecycle.stock, m[before],
                                       m['microlooper_controller_after'], kind))
        lifecycle.to(target)
        lifecycle_records.append((address, lifecycle.stock, target, m[before], kind))
    p.put(BYPASS_FILTER_SITE, pm.thumb_bw(BYPASS_FILTER_SITE, m['microlooper_native_bypass_filter']),
          'selective Atmosphere switch bypass')
    p.put(PARAMETER_FILTER_SITE, pm.thumb_bw(PARAMETER_FILTER_SITE, m['microlooper_native_parameter_filter']),
          'Atmosphere transport snapshot filter')
    p.chain_ptr(TICK_LITERAL, TICK_STOCK, after=m['microlooper_controller_tick'])
    veneer = pm.Asm(p.next())
    veneer.movw_movt(2, stock | 1)
    veneer.movw_movt(3, lp_event | 1 if lp_event else 0)
    veneer.bw(m['microlooper_controller_key'])
    input_veneer = p.add(veneer.bytes())
    hook.to(input_veneer)
    record_bytes = MANIFEST_HEADER.size + 20 * len(lifecycle_records)
    manifest = MANIFEST_HEADER.pack(MANIFEST_MAGIC, 4, record_bytes, m.va, len(module_bytes),
        m['microlooper_controller_key'], m['microlooper_controller_tick'],
        m['microlooper_native_parameter_filter'], m['microlooper_native_bypass_filter'],
        input_veneer, stock, lp_event, m['microlooper_controller_after'], len(lifecycle_records), digest)
    manifest += b''.join(struct.pack('<5I', *record) for record in lifecycle_records)
    manifest_va = p.add(manifest)
    return dict(module_va=m.va, manifest_va=manifest_va, shared_long_press=bool(lp_event),
                **{symbol: m[symbol] for symbol in m.symbols})


def _lifecycle_veneer(at, original, before, after, kind):
    """Four native args, real status to after; original r0/r1 result preserved."""
    import patch_menu as pm
    a = pm.Asm(at)
    a.h(0xb57f)                    # push {r0-r6,lr}:32 aligned bytes
    a.bl(before)
    a.h(0xe89d, 0x000f)           # reload original r0-r3
    a.movw_movt(12, original | 1)
    a.h(0x47e0, 0x4604, 0x460d)  # blx r12; save actual result r0/r1
    a.h(0x4620, 0x9901)           # (result,original r1,operation kind)
    a.movw_movt(2, kind)
    a.bl(after)
    a.h(0x4620, 0x4629, 0xb004, 0xbd70)
    return a.bytes()


def _branch(at, code):
    first, second = struct.unpack('<2H', code)
    if first & 0xf800 != 0xf000 or second & 0xd000 != 0x9000:
        raise ValueError(f'Atmosphere control entry {at:#x} is not a Thumb B.W')
    sign, j1, j2 = (first >> 10) & 1, (second >> 13) & 1, (second >> 11) & 1
    delta = ((sign << 24) | ((1 ^ j1 ^ sign) << 23) | ((1 ^ j2 ^ sign) << 22)
             | ((first & 0x3ff) << 12) | ((second & 0x7ff) << 1))
    return at + 4 + delta - (sign << 25)


def verify_installed(e0):
    """Require exact runtime bytes and real input/tick/filter/lifecycle hooks.

    The manifest is an installation record, not a marker-only permission. This
    validates finalized Entry0 relationships before the separate DSP linker runs.
    """
    import patch_menu as pm
    p = pm.Patch(e0, [], {})
    raw = bytes(e0)
    positions = [n for n in range(len(raw)) if raw.startswith(MANIFEST_MAGIC, n)]
    if len(positions) != 1:
        raise ValueError('Atmosphere controls require exactly one versioned runtime manifest')
    try:
        (magic, version, size, base, code_size, key, tick, parameter, bypass, input_veneer,
         stock, lp_event, after, count, digest) = MANIFEST_HEADER.unpack_from(raw, positions[0])
        if version != 4 or count != len(LIFECYCLE) or size != MANIFEST_HEADER.size + count * 20:
            raise ValueError('unsupported Atmosphere controller manifest layout')
        if digest.hex() != MODULE_SHA256 or hashlib.sha256(p.read(base, code_size)).digest() != digest:
            raise ValueError('Atmosphere controller bytes do not match the verified runtime version')
        symbols = {name: base + offset for name, offset in LAYOUT.items()}
        expected = (symbols['microlooper_controller_key'], symbols['microlooper_controller_tick'],
                    symbols['microlooper_native_parameter_filter'], symbols['microlooper_native_bypass_filter'],
                    symbols['microlooper_controller_after'])
        if (key, tick, parameter, bypass, after) != expected:
            raise ValueError('Atmosphere manifest entry addresses do not match its runtime version')
        for site, target in ((HANDLER, input_veneer), (PARAMETER_FILTER_SITE, parameter), (BYPASS_FILTER_SITE, bypass)):
            if _branch(site, p.read(site, 4)) != target:
                raise ValueError(f'Atmosphere controller hook is missing at {site:#x}')
        a = pm.Asm(input_veneer)
        a.movw_movt(2, stock | 1); a.movw_movt(3, lp_event | 1 if lp_event else 0); a.bw(key)
        if p.read(input_veneer, len(a.bytes())) != a.bytes():
            raise ValueError('Atmosphere input veneer is not the declared shared composition')
        expected_stock = HANDLER_STOCK + pm.thumb_bw(stock + 4, HANDLER + 4)
        if p.read(stock, len(expected_stock)) != expected_stock:
            raise ValueError('Atmosphere input original-handler trampoline is changed')
        if lp_event:
            if p.read(lp_event, 6) != bytes.fromhex('2de9 f041 82b0'):
                raise ValueError('Atmosphere shared long-press target is not lp_event')
        tick_chain = p.u32(TICK_LITERAL)
        if not tick_chain & 1:
            raise ValueError('Atmosphere tick callback is not a Thumb function pointer')
        expected_tick = pm.chain_cave(tick_chain & ~1, TICK_STOCK & ~1, [], [tick])
        if p.read(tick_chain & ~1, len(expected_tick)) != expected_tick:
            raise ValueError('Atmosphere native tick/controller composition is missing')
        records = raw[positions[0] + MANIFEST_HEADER.size:positions[0] + size]
        for index, (site, original, target, before, kind) in enumerate(struct.iter_unpack('<5I', records)):
            native_site, stock_hex, before_name, _ = LIFECYCLE[index]
            expected_kind = 1 if site == 0x28dfc2c4 else 2 if site == 0x28df38d0 else 0
            if site != native_site or before != symbols[before_name] or kind != expected_kind:
                raise ValueError('Atmosphere lifecycle manifest disagrees with native ownership seams')
            if _branch(site, p.read(site, 4)) != target:
                raise ValueError(f'Atmosphere lifecycle hook is missing at {site:#x}')
            stock_bytes = bytes.fromhex(stock_hex)
            expected_tramp = stock_bytes + pm.thumb_bw(original + len(stock_bytes), site + len(stock_bytes))
            if p.read(original, len(expected_tramp)) != expected_tramp:
                raise ValueError('Atmosphere lifecycle original trampoline is changed')
            veneer = _lifecycle_veneer(target, original, before, after, kind)
            if p.read(target, len(veneer)) != veneer:
                raise ValueError('Atmosphere lifecycle status/lock composition is changed')
    except (struct.error, SystemExit, IndexError) as exc:
        raise ValueError(f'Atmosphere runtime manifest is incomplete or unmapped: {exc}') from exc
    return dict(version=version, module_va=base, module_bytes=code_size,
                shared_long_press=bool(lp_event), lifecycle_hooks=count,
                module_sha256=digest.hex())
