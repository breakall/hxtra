"""Checked native declarations for direct-control mono/stereo FX hosts.

This module generates matching model/state/control tables. It does not infer
total arena capacity, implement runtime admission, or choose executable storage.
"""
from dataclasses import asdict, dataclass
import math
import struct

import kit_patch_amp as kit


def uint(value, label, maximum=0xffffffff):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'{label} must be an unsigned integer <= {maximum}')


def native_cost(value):
    if type(value) is not int or not 1 <= value <= 7500:
        raise ValueError('DSP cost must be an explicit integer in 1..7500')
    return value


@dataclass(frozen=True)
class InstanceWords:
    dm_words: int
    pm_words: int
    sdram_words: int

    def __post_init__(self):
        for name, value in asdict(self).items():
            uint(value, name)


@dataclass(frozen=True)
class Parameter:
    name: str
    slot: int
    pid: int
    type: int
    minimum: float
    maximum: float
    default: float
    state_key: str
    state_index: int
    ui_index: int | None
    restore: str = 'value'
    labels: tuple[str, ...] = ()
    follow_enable: bool = False

    def __post_init__(self):
        for name in ('slot', 'pid', 'state_index'):
            uint(getattr(self, name), name)
        if not self.slot or not self.name or not self.state_key:
            raise ValueError('parameter name, state key and nonzero public slot required')
        if type(self.type) is not int or self.type not in (1, 2, 3):
            raise ValueError('parameter type must be native bool=1, int=2 or float=3')
        values = (self.minimum, self.maximum, self.default)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('parameter bounds and default must be finite numbers')
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError('parameter default must lie within its bounds')
        if self.type != 3 and any(type(v) is not int for v in values):
            raise ValueError('integer/bool parameters require integer bounds and default')
        if self.type == 1 and (self.minimum, self.maximum) != (0, 1):
            raise ValueError('bool bounds must be 0..1')
        if self.type == 2 and any(not 0 <= v <= 0xffffffff for v in values):
            raise ValueError('this adapter supports unsigned integer parameters')
        if self.type == 3 and any(abs(v) > 3.4028234663852886e38 for v in values):
            raise ValueError('float parameter must fit float32')
        if self.ui_index is not None:
            uint(self.ui_index, 'ui_index')
        if self.restore not in ('value', 'ignore'):
            raise ValueError('restore must be value or ignore')
        if self.labels and (self.type != 2 or len(self.labels) != self.maximum-self.minimum+1):
            raise ValueError('list labels must cover every integer value')
        if type(self.follow_enable) is not bool or (self.follow_enable and (self.type != 1 or self.ui_index is not None)):
            raise ValueError('native enable follower must be a hidden boolean parameter')

    def native(self):
        word = kit.f2u if self.type == 3 else int
        meta = [('displayName', 7, self.name)]
        if self.labels:
            meta += [('displayType', 7, 'list')]
            meta += [(str(i+self.minimum), 7, label) for i, label in enumerate(self.labels)]
        elif self.type == 1:
            meta += [('false', 7, 'Off'), ('true', 7, 'On')]
        if self.follow_enable:
            meta += [('followEnable', 7, 'true')]
        return dict(slot=self.slot, pid=self.pid, name=self.name, type=self.type,
                    op=kit.NAM_INPUT_OP[self.type], state=self.state_key,
                    raw=[0, 0, 0, self.type, self.slot, word(self.minimum),
                         0 if self.type == 1 else word(self.maximum), word(self.default)],
                    meta=meta, default_word=word(self.default))


@dataclass(frozen=True)
class Callbacks:
    init: str
    control: str
    process: str
    reset: str | None = None
    teardown: str | None = None


@dataclass(frozen=True)
class EffectModel:
    name: str
    display: str
    preset_id: int
    primitive: int
    source_model: str
    host_model: str
    category: int
    folder: str
    width: int
    instance: InstanceWords
    parameters: tuple[Parameter, ...]
    callbacks: Callbacks
    self_bypass: bool = False

    def __post_init__(self):
        uint(self.preset_id, 'preset ID', 832)
        uint(self.primitive, 'primitive ID')
        if not self.preset_id or type(self.width) is not int or self.width not in (1, 2) or self.category not in kit.FX_CATEGORIES:
            raise ValueError('valid preset ID, mono/stereo width and FX category required')
        if not self.parameters:
            raise ValueError('at least one direct parameter required')
        if sum(p.follow_enable for p in self.parameters) > 1:
            raise ValueError('only one native enable follower is supported')
        if type(self.self_bypass) is not bool or (self.self_bypass and not self.follow_enable):
            raise ValueError('self-managed bypass requires a native enable follower')
        for field in ('name', 'slot', 'pid', 'state_key', 'state_index'):
            values = [getattr(p, field) for p in self.parameters]
            if len(set(values)) != len(values):
                raise ValueError(f'duplicate parameter {field}')
        if sorted(p.state_index for p in self.parameters) != list(range(len(self.parameters))):
            raise ValueError('state indices must be dense from zero')
        ordered = sorted(self.parameters, key=lambda p: p.slot)
        shown = [p for p in ordered if p.ui_index is not None]
        if ordered[:len(shown)] != shown or [p.ui_index for p in shown] != list(range(len(shown))):
            raise ValueError('visible parameters must be a slot-ordered UI prefix')
        budget = kit.FX_BUDGET[self.width]
        if any(value > budget[key] for key, value in zip(
                ('dm', 'pm', 'sdram'), asdict(self.instance).values())):
            raise ValueError('instance requests exceed the native FX host budget')

    @property
    def shown(self):
        return sum(p.ui_index is not None for p in self.parameters)

    @property
    def follow_enable(self):
        return any(p.follow_enable for p in self.parameters)

    def native_parameters(self):
        return [p.native() for p in sorted(self.parameters, key=lambda p: p.state_index)]

    def registry(self, symbols):
        def address(name):
            if name is None:
                return 0
            value = symbols[name]
            uint(value, f'callback {name}', 0xffffff)
            if not value:
                raise ValueError('declared callback cannot have a null address')
            return value
        c = self.callbacks
        return [self.primitive, address(c.init), address(c.teardown), address(c.reset),
                address(c.control), address(c.process), self.instance.dm_words, self.instance.pm_words]

    def describe(self):
        parameters = []
        for parameter in sorted(self.parameters, key=lambda p: p.state_index):
            description = asdict(parameter)
            if not parameter.follow_enable:
                del description['follow_enable']
            parameters.append(description)
        description = dict(model_name=self.name, preset_id=self.preset_id, primitive=self.primitive,
                           width=self.width, instance=asdict(self.instance), parameters=parameters,
                           callbacks=asdict(self.callbacks), allocation_scope='primitive payload; not total graph memory')
        if self.self_bypass:
            description['self_bypass'] = True
        return description


def register_model(data, effect, *, dsp_cost, registry_address, log=print):
    """Generate matching Entries0/3/4 using existing checked native writers."""
    native_cost(dsp_cost)
    e0, e3, e4 = (kit.get_entry_swapped(data, i) for i in (0, 3, 4))
    if kit.e0_device(kit._parse_e0_segments(e0)).NAME != 'HX Stomp':
        raise ValueError('effect adapter targets HX Stomp 3.80.0')
    info = kit.parse_entry3_full(e3)
    if any(m['name'] == effect.name for m in info['models']):
        raise SystemExit('effect model is already registered')
    if effect.primitive in kit.stock_prims_in_use(data):
        raise SystemExit('effect primitive is already used by a graph')
    raw = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    if registry_address in kit._scan_e2_injected(raw)[1]:
        raise SystemExit('effect primitive is already hooked')
    src, host = kit.find_model(info, effect.source_model), kit.find_model(info, effect.host_model)
    kit.fx_source_check(e0, src, effect.category, effect.width)
    params = effect.native_parameters()
    new_e4, blob, composite = kit.add_model_entry4(
        e4, host['blob_index'], params, effect.primitive, asdict(effect.instance), fx=True)
    drop = tuple(key for key in kit.FX_MODEL_META_DROP if key != 'displayParamCount')
    new_e3, _, _ = kit.add_model_entry3(
        e3, src, effect.name, effect.display, blob, params, drop_meta=drop,
        display_param_count=effect.shown, follow_enable=effect.follow_enable)
    info = kit.parse_entry3_full(new_e3)
    item = kit.find_model(info, effect.name)
    if kit.pmap_slots_without_param(new_e4, blob, item['params']):
        raise ValueError('parameter map contains undeclared slots')
    new_e0, _, _, _ = kit.add_model_entry0(
        e0, src['words'][2], item['words'][2], effect.display, preset_id=effect.preset_id,
        dsp_cost=dsp_cost, n_params=len(params), folder=(effect.category, effect.folder),
        fx=True, src_category=effect.category)
    new_e0 = bytearray(new_e0)
    segments = kit._parse_e0_segments(new_e0)
    target = kit.e0_device(segments)
    offset = lambda a, n=4: kit._e0_vaddr_to_foff(segments, a, n)
    table, = struct.unpack_from('<I', new_e0, offset(target.TAB2_BASE_PTR))
    _, count = kit._decode_thumb_movw(new_e0[offset(target.TAB2_CNT_INSN):][:4])
    row = offset(table + 44 * (count-1), 44)
    if struct.unpack_from('<I', new_e0, row)[0] != item['words'][2]:
        raise ValueError('generated UI table does not identify the new model')
    struct.pack_into('<3I', new_e0, row+24, effect.shown, len(params), len(params))
    struct.pack_into('<I', new_e0, row+36, int(effect.follow_enable))
    if effect.self_bypass:
        # Native kind24 keeps the DSP graph running while followEnable sends
        # its hidden boolean. Feedbacker and Poly Sustain use the same policy.
        # Change only this new model's browser item, never the source model.
        found = 0
        for subcategory in range(4):
            index = 4*effect.category+subcategory
            pointer, = struct.unpack_from('<I', new_e0, offset(target.BLIST_PTR_TAB+4*index))
            count, = struct.unpack_from('<I', new_e0, offset(target.BLIST_CNT_TAB+4*index))
            for position in range(count if pointer else 0):
                item_offset = offset(pointer+48*position, 48)
                if struct.unpack_from('<I', new_e0, item_offset+4)[0] == item['words'][2]:
                    struct.pack_into('<I', new_e0, item_offset, 24)
                    found += 1
        if found != 1:
            raise ValueError('self-managed effect must have exactly one native browser item')
    expanded, _ = kit.expand_sharc_blob0_buffer(raw)
    out, _, _ = kit.l6ia.rebuild_archive(data, {0: bytes(new_e0), 2: kit.l6ia.swap32(expanded),
                                              3: new_e3, 4: new_e4})
    verify_model(out, effect)
    log(f'[+] {effect.display}: preset {effect.preset_id}, cost {dsp_cost}, instance {asdict(effect.instance)}')
    return out, dict(model_id=item['model_id'], blob=blob, composite=composite,
                     preset_id=effect.preset_id, dsp_cost=dsp_cost, instance=asdict(effect.instance))


def verify_model(data, effect):
    """Read back raw defaults, persisted order, UI, graph and native cost."""
    e0, e3, e4 = (kit.get_entry_swapped(data, i) for i in (0, 3, 4))
    info = kit.parse_entry3_full(e3)
    item = kit.find_model(info, effect.name)
    params = effect.native_parameters()
    if len(item['params']) != len(params) or item['meta'].get('displayParamCount') != str(effect.shown):
        raise ValueError('effect parameter contract is changed')
    if item['meta'].get('followEnable') != ('true' if effect.follow_enable else None):
        raise ValueError('effect native enable-following policy is changed')
    for actual, expected in zip(item['params'], params):
        if ((actual['name'], actual['slot'], actual['type']) !=
                (expected['name'], expected['slot'], expected['type']) or
                list(struct.unpack_from('<8I', e3, actual['off']))[3:] != expected['raw'][3:] or
                actual['meta'] != {k: v for k, _, v in expected['meta']}):
            raise ValueError('effect parameter contract, bounds, defaults or labels are changed')
    if item['words'][6] != len(params):
        raise ValueError('effect persisted-state count is changed')
    for i, p in enumerate(params):
        _, _, name, ty, index = struct.unpack_from('<5I', e3, item['words'][10]+20*i)
        if name >= len(info['strings']) or (info['strings'][name], ty, index) != (p['state'], p['type'], i):
            raise ValueError('effect persisted-state mapping is changed')
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    blob = kit.entry4_blob.blob(words, 0)
    model_blob = kit.entry4_blob.blob(words, item['blob_index'])
    composite = kit.entry4_blob.top_type(model_blob)
    if list(model_blob) != kit.nam_host_blob(composite, params):
        raise ValueError('effect parameter map, slot/PID routing or defaults are changed')
    graph = kit.entry4_blob.parse_composite(blob, composite)
    member = graph['members'][1]
    record = graph['members_off']+20
    expected = (effect.primitive, effect.width, effect.width, effect.instance.dm_words,
                effect.instance.pm_words, effect.instance.sdram_words, 0)
    actual = (member['type_id'], member['n_in'], member['n_out'], member['dm_words'],
              member['pm_words'], blob[record+15], member['n_init'])
    if actual != expected:
        raise ValueError('effect native instance contract or history allocation is changed')
    segments = kit._parse_e0_segments(e0)
    target = kit.e0_device(segments)
    if target.NAME != 'HX Stomp':
        raise ValueError('effect adapter targets HX Stomp 3.80.0')
    def read(address, size=4):
        off = kit._e0_vaddr_to_foff(segments, address, size)
        return e0[off:off+size]
    table, = struct.unpack('<I', read(target.TAB1_BASE_PTRS[0]))
    _, count = kit._decode_thumb_movw(read(target.TAB1_CNT_INSN))
    matches = [row for i in range(count)
               if (row := struct.unpack('<IHHI', read(table+12*i, 12)))[0] == item['words'][2]]
    if len(matches) != 1 or matches[0][1] != effect.preset_id:
        raise ValueError('effect model identity is changed')
    native_cost(matches[0][3])
    table, = struct.unpack('<I', read(target.TAB2_BASE_PTR))
    _, count = kit._decode_thumb_movw(read(target.TAB2_CNT_INSN))
    ui = [row for i in range(count) if (row := read(table+44*i, 44))[:4] == struct.pack('<I', item['words'][2])]
    if len(ui) != 1 or struct.unpack_from('<3I', ui[0], 24) != (effect.shown, len(params), len(params)):
        raise ValueError('effect UI parameter counts are changed')
    if struct.unpack_from('<2I', ui[0], 36) != (int(effect.follow_enable), 0):
        raise ValueError('effect native enable-following or meter policy is changed')
    if effect.self_bypass:
        kinds = []
        for subcategory in range(4):
            index = 4*effect.category+subcategory
            pointer, = struct.unpack('<I', read(target.BLIST_PTR_TAB+4*index))
            count, = struct.unpack('<I', read(target.BLIST_CNT_TAB+4*index))
            kinds += [row[0] for position in range(count if pointer else 0)
                      if (row := struct.unpack('<2I', read(pointer+48*position, 8)))[1] == item['words'][2]]
        if kinds != [24]:
            raise ValueError('effect self-managed native bypass policy is changed')
    return item, matches[0][3]
