"""Native planar bridge, audio behavior and caller register preservation."""
import random

import numpy as np
import pytest

import microlooper_audio as audio
import microlooper_adapter as adapter
import microlooper_bridge as bridge
import sasm
import ssim


def signal(frame):
    return (((frame*37)%127-63)/256, ((frame*19)%113-56)/256)


@pytest.mark.parametrize('mode',[0,1,2])
@pytest.mark.parametrize('inplace',[False,True])
def test_planar_bridge_is_bit_exact_to_encoded_core_through_transport(mode,inplace):
    native=bridge.Bridge();core=audio.Audio()
    controls=dict(mode=mode,length=.63,modify=.8125,clock=1,mix=.8)
    native.params(**controls);core.params(**controls)
    for first in range(0,640,16):
        changes={}
        if first==64:changes['play']=True
        if first==128:changes['overdub']=True
        if first==224:changes['overdub']=False
        if first==256:changes['length']=.05
        if first==320:changes.update(mode=(mode+1)%3,clock=.5)
        if first==384:changes['play']=False
        if first==448:changes['play']=True
        if changes:native.params(**changes);core.params(**changes)
        samples=[signal(i) for i in range(first,first+16)]
        np.testing.assert_array_equal(native.block(samples,inplace=inplace),core.block(samples))
    for offset in range(audio.RING_WORDS):
        assert native.sim.rd(native.ring+offset)==core.sim.rd(core.ring+offset)


def register_state(sim):
    return ([sim.R(r) for r in range(16)],list(sim.alt),
            [sim.get(c) for c in range(0x10,0x50)],
            sim.u[ssim.U_MODE1],sim.get(ssim.U_ASTATX),sim.get(ssim.U_ASTATY),
            sim.get(sasm.UREG_CODE['STKYX']),sim.get(sasm.UREG_CODE['STKYY']))


@pytest.mark.parametrize('invalid_extent',[False,True])
@pytest.mark.parametrize('channels',[1,2])
def test_bridge_preserves_arguments_dag_metadata_registers_modes_and_status(invalid_extent,channels):
    native=bridge.Bridge(channels=channels);sim=native.sim
    rng=random.Random(335)
    for r in range(16):sim.setR(r,rng.getrandbits(32));sim.alt[r]=rng.getrandbits(32)
    for code in range(0x10,0x50):
        sim.set(code,rng.randrange(1,16) if 0x30<=code<0x40 else rng.randrange(0x100000))
    for code,value in ((0x10,native.state),(0x11,0xb8000),(0x12,0xb8100),(0x13,native.call_record)):
        sim.set(code,value)
    sim.u[ssim.U_MODE1]=0x1608000
    sim.set(ssim.U_ASTATX,0x13579001);sim.set(ssim.U_ASTATY,0x2468abc0)
    sim.set(sasm.UREG_CODE['STKYX'],0xdead0137)
    sim.set(sasm.UREG_CODE['STKYY'],0xcafe2468)
    if invalid_extent:sim.wr(native.instance+7,native.ring+16)
    before=register_state(sim)
    native.block([.2]*16 if channels==1 else [(.2,-.3)]*16)
    assert register_state(sim)==before
    assert not sim.pcstk and not sim.loops


def test_sticky_status_restored_even_when_callee_changes_it(monkeypatch):
    native=bridge.Bridge();sim=native.sim
    sticky=[sasm.UREG_CODE[name] for name in ('STKYX','STKYY')]
    original=[0xdead0137,0xcafe2468]
    for register,value in zip(sticky,original):sim.set(register,value)
    core_entry=audio.assemble()[1][audio.ENTRY]
    step=sim.step
    def clobber_sticky_in_core():
        if sim.pc==core_entry:
            for register,value in zip(sticky,original):sim.set(register,value^0xffffffff)
        return step()
    monkeypatch.setattr(sim,'step',clobber_sticky_in_core)
    native.block()
    assert [sim.get(register) for register in sticky]==original


@pytest.mark.parametrize('field,pointer', [
    *((field, pointer) for field in ('call', 'instance')
      for pointer in (0, 0xfffffff0, 0xa0000, 0xd0000)),
    ('instance', 0x30d100-1), ('instance', 0x324497-7), ('instance', 0x324497),
])
def test_invalid_descriptor_is_rejected_before_dereference(monkeypatch, field, pointer):
    # Bank endpoints are covered below. These add null/wraparound, interior
    # gaps in each folded window, and the separate Heap6 instance boundaries.
    native = bridge.Bridge(**({'call_record': pointer} if field == 'call' else {'instance': pointer}))
    rd = native.sim.rd
    forbidden = {pointer+2} if field == 'call' else {pointer+6, pointer+7}
    def checked(address):
        assert address & 0xffffffff not in {value & 0xffffffff for value in forbidden}
        return rd(address)
    monkeypatch.setattr(native.sim, 'rd', checked)
    samples = [(.125, -.25)]*16
    assert native.block(samples) == samples
    assert native.sim.rd(native.state+audio.ERRORS) == 1


@pytest.mark.parametrize('field,words',[('call',3),('instance',8)])
@pytest.mark.parametrize('low,high',adapter.INTERNAL_DM_RANGES)
@pytest.mark.parametrize('edge',['first','last','before','crossing','after'])
def test_whole_descriptor_must_fit_one_real_sram_bank(monkeypatch,field,words,low,high,edge):
    pointer={'first':low,'last':high-words,'before':low-1,
             'crossing':high-words+1,'after':high}[edge]
    valid=edge in ('first','last')
    native=bridge.Bridge(**({'call_record':pointer} if field=='call' else {'instance':pointer}))
    if not valid:
        rd=native.sim.rd
        forbidden={pointer+2} if field=='call' else {pointer+6,pointer+7}
        def checked(address):
            assert address & 0xffffffff not in forbidden
            return rd(address)
        monkeypatch.setattr(native.sim,'rd',checked)
    samples=[(.125,-.25)]*16
    assert native.block(samples)==samples
    assert native.sim.rd(native.state+audio.ERRORS)==int(not valid)
    assert native.sim.rd(native.state+audio.INITIALIZED)==int(valid)


@pytest.mark.parametrize('begin,end',[(0,48000),(0x400000,0x400002),(0x400000,0x3fffff),
                                      (0x1fffff,0x400000),(0x400000,0x4000001)])
def test_invalid_extent_is_dry_without_audio_ring_access(monkeypatch,begin,end):
    native=bridge.Bridge();native.sim.wr(native.instance+6,begin);native.sim.wr(native.instance+7,end)
    writes=[];wr=native.sim.wr
    def checked(address,value):
        writes.append(address&0xffffffff);return wr(address,value)
    monkeypatch.setattr(native.sim,'wr',checked)
    samples=[(.25,-.125)]*16
    assert native.block(samples)==samples
    assert not any(native.ring<=address<native.ring+audio.RING_WORDS for address in writes)
    assert native.sim.rd(native.state+audio.ERRORS)==1


def test_private_state_ring_native_buffer_guards_and_stereo_isolation():
    native=bridge.Bridge();sim=native.sim
    for address in (native.state-1,native.state+bridge.STATE_WORDS,native.ring-1,
                    native.ring+audio.RING_WORDS,0xb8000-1,0xb8000+32,0xb8100-1,0xb8100+32):
        sim.wr(address,0xdeadbeef)
    native.params(mix=1)
    for _ in range(4):native.block([(.25,0.)]*16)
    native.params(play=True)
    for _ in range(16):
        output=native.block()
        assert all(right==0 for _,right in output)
    for address in (native.state-1,native.state+bridge.STATE_WORDS,native.ring-1,
                    native.ring+audio.RING_WORDS,0xb8000-1,0xb8000+32,0xb8100-1,0xb8100+32):
        assert sim.rd(address)==0xdeadbeef
    # Native shape metadata is owned by the caller and not overwritten.
    assert sim.rd(native.state)==16 and sim.rd(native.state+2)==2


def test_two_instances_keep_their_own_private_history():
    first=bridge.Bridge();second=bridge.Bridge(state=0xb4000,ring=0x420000,
                                             call_record=0xb6100,instance=0x9a100,sim=first.sim)
    first.block([(.25,0.)]*16);second.block([(0.,-.125)]*16)
    assert first.sim.rd(first.ring)==ssim.f2b(.25)
    assert first.sim.rd(first.ring+1)==0
    assert second.sim.rd(second.ring)==0
    assert second.sim.rd(second.ring+1)==ssim.f2b(-.125)
    assert first.sim.rd(first.state+audio.RECORDED)==16
    assert second.sim.rd(second.state+audio.RECORDED)==16


def test_relocated_bridge_calls_explicit_relocated_core_entry():
    native=bridge.Bridge(core_base=0xe4000,bridge_base=0xe3800)
    assert native.symbols[bridge.ENTRY]==0xe3800
    samples=[signal(i) for i in range(16)]
    assert native.block(samples)==samples
    assert native.sim.rd(native.state+audio.INITIALIZED)==1
    assert native.sim.rd(native.state+audio.RECORDED)==16


def test_bridge_rejects_invalid_code_addresses():
    for base,core in [(-1,0xe3000),(0xe3501,0xe3000),(0xe3500,-1)]:
        with pytest.raises(ValueError):bridge.assemble(base,core)


@pytest.mark.parametrize('instance',[0x30d100,0x324497-8])
def test_native_heap6_instance_descriptor_binds_history_and_runs_audio(instance):
    native=bridge.Bridge(instance=instance)
    samples=[signal(i) for i in range(16)]
    np.testing.assert_array_equal(native.block(samples),samples)
    assert native.sim.rd(native.state+12)==native.ring
    assert native.sim.rd(native.state+13)==native.ring+audio.RING_WORDS
    assert native.sim.rd(native.state+20)==1
    assert native.sim.rd(native.state+22)==16


@pytest.mark.parametrize('mode', [0, 1, 2])
@pytest.mark.parametrize('inplace', [False, True])
def test_mono_native_bridge_matches_direct_core_and_owns_half_ring(mode, inplace):
    native, core = bridge.Bridge(channels=1), audio.Audio(channels=1)
    for effect in (native, core):
        effect.params(mode=mode, mix=.8, modify=.1875, length=.63)
    for first in range(0, 384, 16):
        changes = {}
        if first == 64: changes['play'] = True
        if first == 128: changes['overdub'] = True
        if first == 192: changes['overdub'] = False
        if first == 224: changes.update(mode=(mode+1)%3, clock=.5)
        if changes:
            native.params(**changes)
            core.params(**changes)
        samples = [signal(frame)[0] for frame in range(first, first+16)]
        assert native.block(samples, inplace=inplace) == core.block(samples)
    assert native.sim.rd(native.state + audio.CHANNELS) == 1
    assert native.sim.rd(native.state + audio.RING_END) - native.ring == 24000
    assert [native.sim.rd(native.ring+i) for i in range(24000)] == [core.sim.rd(core.ring+i) for i in range(24000)]
