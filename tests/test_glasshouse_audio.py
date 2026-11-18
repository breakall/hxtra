"""Execute emitted Glasshouse ISA48 against the pinned, independent C++ engine."""
import math
import random

import numpy as np
import pytest

import glasshouse_audio as audio
import glasshouse_state as state
from glasshouse import reference
import ssim


@pytest.fixture(scope='module')
def oracle(tmp_path_factory):
    return reference.build_reference(tmp_path_factory.mktemp('glasshouse-oracle'))


def signal(n):
    i=np.arange(n,dtype=np.float32)
    # Separate spectra and transients reveal wrong linkage, routing and timing.
    left=(np.sin(i*.173)*.37+np.sin(i*.713)*.08)*(1.-((i//73)%3)*.27)
    right=np.cos(i*.391)*.23+np.sin(i*.037)*.11
    return np.column_stack((left,right)).astype(np.float32)


def render(engine,frames,*,inplace=False):
    return np.asarray([sample for first in range(0,len(frames),16)
                       for sample in engine.block(frames[first:first+16],inplace=inplace)])


def config(case):
    knobs=[list(p) for p in reference.KNOBS]
    toggles=[list(p) for p in reference.TOGGLES]
    knobs[0][0]=.72;knobs[0][1]=.65;knobs[0][3]=.08
    toggles[2][0]=1
    if case=='default':return reference.KNOBS,reference.TOGGLES
    if case=='sag':knobs[0][1]=.97
    if case=='gentle':toggles[0][2]=0
    if case=='lively':toggles[0][2]=2
    if case=='dark_dynamic':knobs[0][4]=.08;toggles[0][1]=0
    if case=='bass_motion':knobs[0][4]=.93;toggles[0][1]=2
    if case=='emphasis_adaptive':toggles[1][2]=2;toggles[1][0]=2
    if case=='short_release':toggles[0][0]=0;toggles[1][0]=0
    if case=='long_release':toggles[0][0]=2;toggles[1][0]=1
    if case=='sidechain_hpf':toggles[2][0]=2;knobs[1][5]=.8
    if case=='independent':toggles[2][2]=1
    if case=='spread_eq':toggles[2][2]=2;toggles[1][1]=0;knobs[0][4]=.1
    if case=='spread_volume':toggles[2][2]=2;toggles[1][1]=2;knobs[2][3]=1.
    if case=='gate_swell':knobs[2][2]=1.;toggles[2][1]=2;knobs[1][2]=0.;knobs[1][3]=0.
    if case=='drive':knobs[2][4]=1.;knobs[0][2]=.9;knobs[0][5]=.2
    if case.startswith('automation'):
        knobs[2][1]=1.;knobs[3]=[.4,.8,.2,.5,.6,.1]
        toggles[3]=[2,{'automation_linear':0,'automation_cosine':1,'automation_step':2}[case],{'automation_linear':0,'automation_cosine':1,'automation_step':2}[case]]
    return knobs,toggles


@pytest.mark.parametrize('case',['default','sag','gentle','lively','dark_dynamic','bass_motion',
    'emphasis_adaptive','short_release','long_release','sidechain_hpf','independent',
    'spread_eq','spread_volume','gate_swell','drive','automation_linear','automation_cosine','automation_step'])
def test_encoded_modes_match_independent_source(oracle,case,monkeypatch):
    monkeypatch.setattr(ssim,'RECIPS_HW',True)
    knobs,toggles=config(case)
    frames=signal(256)
    expected=reference.run(oracle,reference.settings(knobs,toggles,reset=True),
                           reference.switch('enable',True),reference.process(frames))
    engine=audio.Audio();engine.settings(knobs,toggles)
    actual=render(engine,frames,inplace=True)
    # ADAA differences amplify binary32 library rounding near its delta cutoff.
    tolerance=1.e-4 if case=='drive' else 1.e-5
    np.testing.assert_allclose(actual,expected,atol=tolerance,rtol=0)


@pytest.mark.parametrize('channels',[1,2])
def test_process_preserves_registers_modes_and_instance_bounds(channels):
    engine=audio.Audio(channels=channels);sim=engine.sim;rng=random.Random(44)
    for r in range(16):sim.setR(r,rng.getrandbits(32));sim.alt[r]=rng.getrandbits(32)
    for c in range(0x10,0x50):sim.set(c,rng.randrange(1,16) if 0x30<=c<0x40 else rng.randrange(0x100000))
    for c,v in ((0x10,engine.state),(0x11,0xb8000),(0x12,0xb8100)):sim.set(c,v)
    sim.u[ssim.U_MODE1]=0x1608000
    sim.wr(engine.state-1,0xdeadbeef);sim.wr(engine.state+audio.STATE_WORDS,0xfeedface)
    before=([sim.R(r) for r in range(16)],list(sim.alt),[sim.get(c) for c in range(0x10,0x50)],sim.get(ssim.U_MODE1))
    writes=[];original=sim.wr
    def checked(address,value):
        writes.append(address)
        assert engine.state<=address<engine.state+audio.STATE_WORDS or 0xb8000<=address<0xb8020 or 0xb8100<=address<0xb8120
        original(address,value)
    sim.wr=checked
    engine.block([.125]*16 if channels==1 else [(.125,-.25)]*16)
    after=([sim.R(r) for r in range(16)],list(sim.alt),[sim.get(c) for c in range(0x10,0x50)],sim.get(ssim.U_MODE1))
    assert before==after
    assert sim.rd(engine.state-1)==0xdeadbeef and sim.rd(engine.state+audio.STATE_WORDS)==0xfeedface
    assert max(writes)<engine.state+audio.STATE_WORDS or max(writes)<0xb8120


def test_two_instances_and_code_relocation_are_independent(oracle):
    frames=signal(64)
    first=audio.Audio(base=0x218000,state_address=0xb3000)
    second=audio.Audio(base=0x218000,state_address=0xb4000,sim=first.sim)
    second.params(dynamics=.9,sag=True)
    actual1=[];actual2=[]
    for p in range(0,len(frames),16):
        actual1.extend(first.block(frames[p:p+16]));actual2.extend(second.block(frames[p:p+16]))
    expected=reference.run(oracle,reference.settings(reset=True),reference.switch('enable',True),reference.process(frames))
    np.testing.assert_allclose(actual1,expected,atol=1e-5,rtol=0)
    assert not np.array_equal(actual1,actual2)


def test_sag_aux_and_enable_edges_match_source(oracle):
    knobs,toggles=config('sag')
    knobs[1][2]=0.;knobs[1][3]=0.;toggles[2][1]=1
    chunks=[signal(128) for _ in range(8)]
    actions={1:('aux',True),2:('aux',False),3:('sag',True),4:('sag',False),5:('enable',False),6:('enable',True)}
    commands=[reference.settings(knobs,toggles,reset=True),reference.switch('enable',True)]
    engine=audio.Audio();engine.settings(knobs,toggles);actual=[]
    for i,frames in enumerate(chunks):
        if i in actions:
            name,value=actions[i];commands.append(reference.switch(name,value));engine.params(**{name:value})
        commands.append(reference.process(frames));actual.extend(render(engine,frames))
    expected=reference.run(oracle,*commands)
    np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=0)


def test_silence_and_zero_dynamics_unity_are_finite(oracle):
    knobs,toggles=config('default');knobs=[list(x) for x in knobs];toggles=[list(x) for x in toggles]
    knobs[0][1]=0.;toggles[1][0]=0
    frames=np.vstack((np.zeros((128,2),dtype=np.float32),signal(128)))
    engine=audio.Audio();engine.settings(knobs,toggles)
    actual=render(engine,frames)
    expected=reference.run(oracle,reference.settings(knobs,toggles,reset=True),reference.switch('enable',True),reference.process(frames))
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(actual,expected,atol=1e-6,rtol=0)


@pytest.mark.parametrize('name,values,expected,tolerance',[
    ('gh_exp',[-20.,-8.,-.7,0.,.7,2.,10.],math.exp,2e-6),
    ('gh_log',[1e-12,.001,.1,.5,1.,1.99,10.,1000.],math.log,2e-6),
    ('gh_log1p',[0.,1e-9,.001,.1,1.,10.,250.538,1000.],math.log1p,1e-6),
    ('gh_sin',[-6.28,-3.14,-1.57,-.1,0.,.1,1.57,3.14,6.28,9.42],math.sin,5e-7),
    ('gh_tan',[0.,.001,.1,.5,.9,1.1781],math.tan,2e-6),
])
def test_encoded_scalar_math_against_host_library(name,values,expected,tolerance,monkeypatch):
    monkeypatch.setattr(ssim,'RECIPS_HW',True)
    engine=audio.Audio()
    for value in values:
        value=ssim.b2f(ssim.f2b(value))
        engine.sim.set(0x10,engine.state);engine.sim.set(0,ssim.f2b(value))
        engine.sim.call(engine.symbols[name.upper()],limit=500)
        actual=ssim.b2f(engine.sim.get(0))
        assert abs(actual-expected(value))<=tolerance*max(1.,abs(expected(value)))


def test_long_steady_compression_matches_source_without_gain_oscillation(oracle):
    knobs,toggles=config('short_release')
    toggles[2][0]=0;knobs[0][0]=.52;knobs[0][1]=.5;knobs[0][3]=0.
    n=4096;i=np.arange(n,dtype=np.float32)
    frames=(.35*np.sin(2*np.pi*110*i/48000)).astype(np.float32)
    expected=reference.run(oracle,reference.settings(knobs,toggles,reset=True),reference.switch('enable',True),reference.process(frames))[:,0]
    engine=audio.Audio(channels=1);engine.settings(knobs,toggles)
    actual=render(engine,frames)
    np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=0)
    assert np.sqrt(np.mean(actual[-512:]**2))<.2


def test_settings_updates_and_long_bounce_match_source(oracle):
    knobs,toggles=config('automation_cosine')
    # Keep the independent oracle's complete source automation running through
    # a full bounce period, then change sound settings without resetting state.
    frames=signal(6144)
    changed=[list(p) for p in knobs];changed[0][4]=.1;changed[0][3]=.8;changed[1][5]=.6
    engine=audio.Audio(channels=1);engine.settings(knobs,toggles)
    mono=frames[:,0]
    actual=np.concatenate((render(engine,mono[:3072]),))
    engine.settings(changed,toggles)
    actual=np.concatenate((actual,render(engine,mono[3072:])))
    expected=reference.run(oracle,reference.settings(knobs,toggles,reset=True),reference.switch('enable',True),
        reference.process(mono[:3072]),reference.settings(changed,toggles),reference.process(mono[3072:]))[:,0]
    np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=0)



def test_compensated_adaa_input_division_matches_binary32_rounding(monkeypatch):
    monkeypatch.setattr(ssim,'RECIPS_HW',True)
    engine=audio.Audio();engine.sim.set(0x10,engine.state);rng=random.Random(76)
    # High parallel levels and minimum drive ceiling produced the reviewed
    # antiderivative error when a reciprocal product missed a/b by one ULP.
    pairs=[(8.*.99034,.03162277489900589),(0.,.03162277489900589)]
    pairs += [(rng.uniform(-8.,8.),rng.uniform(.025,.71)) for _ in range(100)]
    for numerator,denominator in pairs:
        numerator,denominator=(ssim.b2f(ssim.f2b(v)) for v in (numerator,denominator))
        engine.sim.set(0,ssim.f2b(numerator));engine.sim.set(1,ssim.f2b(denominator))
        engine.sim.call(engine.symbols['GH_DIVIDE'],limit=1000)
        assert engine.sim.get(0)==ssim.f2b(numerator/denominator)
