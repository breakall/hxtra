"""Bound encoded callback memory traffic and check live cache invalidation."""
import numpy as np
import pytest

import glasshouse_audio as audio
from glasshouse import reference
import ssim


@pytest.fixture(scope='module')
def oracle(tmp_path_factory):
    return reference.build_reference(tmp_path_factory.mktemp('glasshouse-optimization'))


@pytest.mark.parametrize('width,read_budget,write_budget',[(1,4000,2000),(2,6500,3000)])
def test_warm_default_callback_meets_memory_traffic_budget(width,read_budget,write_budget,monkeypatch):
    monkeypatch.setattr(ssim,'RECIPS_HW',True)
    engine=audio.Audio(channels=width)
    samples=[.25]*16 if width==1 else[(.25,-.125)]*16
    engine.block(samples)
    active=[False];counts=[0,0]
    original_call,original_read,original_write=engine.sim.call,engine.sim.rd,engine.sim.wr
    def call(*args,**kwargs):
        active[0]=True
        try:return original_call(*args,**kwargs)
        finally:active[0]=False
    def read(address):
        counts[0]+=int(active[0]);return original_read(address)
    def write(address,value):
        counts[1]+=int(active[0]);original_write(address,value)
    engine.sim.call,engine.sim.rd,engine.sim.wr=call,read,write
    engine.block(samples)
    assert counts[0]<=read_budget,counts
    assert counts[1]<=write_budget,counts


@pytest.mark.parametrize('width',[1,2])
def test_changed_coefficients_match_source_and_resume_warm_cost(oracle,width,monkeypatch):
    monkeypatch.setattr(ssim,'RECIPS_HW',True)
    knobs=[list(page) for page in reference.KNOBS]
    toggles=[list(page) for page in reference.TOGGLES]
    knobs[0][0],knobs[0][1],knobs[0][3]=.62,.75,.1
    knobs[2][2]=1.
    toggles[2][0]=1
    i=np.arange(256,dtype=np.float32)
    frames=np.column_stack((.4*np.sin(i*.173),-.31*np.cos(i*.327))).astype(np.float32)
    if width==1:frames=frames[:,0]
    engine=audio.Audio(channels=width);engine.settings(knobs,toggles)
    commands=[reference.settings(knobs,toggles,reset=True),reference.switch('enable',True)]
    actual=[];work=[]
    for first in range(0,len(frames),16):
        if first==64:
            knobs[0][3],knobs[1][0],knobs[1][1],knobs[1][4],knobs[1][5]=.9,.8,.2,.1,.7
            toggles[0][0],toggles[1][2]=1,2
        if first in (64,96):
            # Same-state delivery at96 must not reset envelopes or waste another
            # coefficient evaluation; the independent source recalculation has
            # the same result and retains its audio history.
            engine.settings(knobs,toggles);commands.append(reference.settings(knobs,toggles))
        block=frames[first:first+16]
        commands.append(reference.process(block))
        before=engine.sim.cycles;actual.extend(engine.block(block,inplace=True));work.append(engine.sim.cycles-before)
    expected=reference.run(oracle,*commands)
    if width==1:expected=expected[:,0]
    np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=0)
    assert work[4]-max(work[5:8])>300,work
