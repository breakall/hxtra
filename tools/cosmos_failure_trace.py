#!/usr/bin/env python3
"""Bounded, read-only native M4 Cosmos graph-request and failure replay.

Runs original stock instructions using Unicorn, synthetic model metadata, stream
I/O and operating-system hooks. Negative local create statuses are explicit
injections, not substituted SHARC allocation outcomes. Receiver cases exercise
the real token discriminator and pending-status store independently.

No device access, firmware mutation or reconstructed DSP implementation occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'tools')]
import m4emu
import patch_amp as pa
from firmware import reader


def trace(path):
    e0 = pa.get_entry_swapped(pa.load_l6ia_from_any(str(path))[0], 0)
    read = reader(e0)
    source_md5 = hashlib.md5(path.read_bytes()).hexdigest()
    if source_md5 != 'a2cd8f4ae56f49415380270ebc484bf1':
        raise ValueError('This address-bound replay requires the supplied stock HX Stomp 3.80.0 HXF')
    report = {
        'artifact_md5': source_md5,
        'entry0_sha256': hashlib.sha256(e0).hexdigest(),
        'runtime': 'Unicorn ' + m4emu.unicorn.__version__,
        'cases': [],
        'limitations': [
            'Offline native M4 execution only. No physical transport or SHARC allocation occurred.',
            'Model metadata, locks and external platform hooks are explicit fixtures. Native graph-create call negatives are conditional propagation evidence, not substituted remote allocator outcomes.',
            'The native request and receiver were executed separately. Token -2 replies are ignored; a real SHARC allocation reply was not observed.',
            'Previous-graph release is observed at its virtual interface call. Remote opcode15 execution and storage reclamation are outside this probe.',
        ],
    }
    APP,PRESET,OLD,NEW,DESC,CTX,BACK,SLOT,MODEL,META,OUT= [0x28600000+i*0x10000 for i in range(11)]

    def s(v):return v if v<2**31 else v-2**32

    def fresh(descriptor_address=0x28011580):
        m=m4emu.M4(b'',0x28f10000)
        # Targeted actual instruction spans, never arbitrary full-image executable permission.
        for a,n in [(0x28dfc2c4,0x69c),(0x28df5198,0x2a0),(0x28df5438,0xf8),(0x28dfcc48,0x188),(0x28dfcba8,0xa0),(0x28dfa774,0x20),(0x28da9f44,0xa8),(0x28da7190,0x20),(0x28da7090,0xbc)]:m.load(a,read(a,n))
        m.u32(APP,PRESET);m.u32(APP+4,META);m.u32(APP+12,MODEL)
        for p in [OLD,NEW]:
            m.u32(p+0x24,3);m.u8(p+0x28,8);m.u32(p+0x30,CTX);m.u32(p+0x34,CTX)
        m.u32(OLD,12);m.u32(NEW,13);m.u32(OLD+0x9f0,SLOT);m.u32(NEW+0x9f0,SLOT)
        m.u32(SLOT+4,OLD);m.u32(SLOT+8,BACK);m.u32(BACK,PRESET);m.u32(SLOT+16,7)
        m.write(DESC,read(descriptor_address,0x30));m.u32(META+36+4*12,OLD);m.u32(META+36+4*13,NEW)
        # Common explicit local environment fixtures.
        def stub(a,h=None):
            def f(x):
                if h:h(x)
                else:x.reg('r0',0)
            m.stub(a,f)
        def outarg2(x):x.u32(x.reg('r2'),OLD);x.reg('r0',0)
        stub(0x28dfa864,outarg2)
        def check(x):x.u8(x.stack_args(1)[0],1);x.reg('r0',0)
        stub(0x28e249a0);stub(0x28e24a30);stub(0x28dfa9a4,check);stub(0x28dfa434);stub(0x28df4d24,lambda x:x.reg('r0',NEW))
        stub(0x28df35e0);stub(0x28df4cd8);stub(0x28e006cc)
        stub(0x28dfa720);stub(0x28da6d5c,lambda x:x.reg('r0',1));stub(0x28da6d30)
        stub(0x28dffa90,lambda x:x.reg('r0',0))
        def lookup(x):x.u32(x.reg('r3'),0);x.reg('r0',0)
        stub(0x28df3594,lookup)
        def baseparam(x):x.u32(x.reg('r3'),1);x.reg('r0',0)
        stub(0x28df35a0,baseparam)
        def child(x):x.u32(x.reg('r3'),CTX);x.reg('r0',0)
        stub(0x28df3558,child)
        return m,stub

    # Follow actual member-release and opcode3 packaging through real virtual entry7190.
    for fail_at in [None,0,1,2]:
        for error in ([-19,-42] if fail_at is not None else [0]):
            m,stub=fresh();graph=CTX;owner=BACK;vt=OUT;stream=MODEL;svt=META;fn=0x28f10020;free=0x28f10040
            m.u32(graph,owner);m.u32(graph+4,0x2468);m.u32(graph+20,0);m.u32(graph+24,0x1234)
            m.u32(owner+16,vt);m.u32(vt+8,0x28da7191);m.u32(vt+52,free|1);m.u32(owner+20,stream);m.u32(stream,svt);m.u32(svt+4,fn|1)
            frames=[];frees=[]
            def freefn(x):frees.append([x.reg('r0'),x.reg('r1')]);x.reg('r0',0)
            stub(free,freefn)
            def tx(x):
                b=x.read(x.reg('r1'),x.reg('r2'));i=len(frames);frames.append({'size':len(b),'words':[hex(v) for v in struct.unpack('<'+'I'*(len(b)//4),b)]});x.reg('r0',error if i==fail_at else len(b))
            stub(fn,tx)
            m.u32(DESC,DESC+0x100);m.u32(DESC+0x100,0x28f10061)
            def blobread(x):x.write(x.reg('r1'),b'ABCDWXYZ'[:x.reg('r2')]);x.reg('r0',min(8,x.reg('r2')))
            stub(0x28f10060,blobread)
            result=m.call(0x28da9f44,graph,DESC,8,0xfffffffe)
            assert s(result)==(error if fail_at is not None else 8)
            assert m.u32(graph+20)==0 and m.u32(graph+24)==0 and len(frees)==1
            report['cases'].append({'case':'graph_request_transport','injected_write':fail_at,'injected_status':error,'status':s(result),'frames':frames,'previous_graph_release_requested':True,'private_allocation_cleared':True})

    # Execute Cosmos constructor, then enclosing insertion or replacement. Fail at native graph-create call2,
    # after parent graph-create call1 succeeded, not at a replacement-specific status stub.
    for descriptor_address in [0x28011580,0x28011a90]:
        for outer in ['constructor','insert','replace','preset_existing','preset_new']:
            for error in [-19,-42,-4]:
                m,stub=fresh(descriptor_address);creates=[]
                def create(x):creates.append((x.reg('r0'),x.reg('r1'),x.reg('r2')));x.reg('r0',error if len(creates)==2 else 0)
                stub(0x28df35d8,create)
                if outer=='constructor':result=m.call(0x28dfc2c4,APP,NEW,DESC)
                elif outer=='insert':
                    m.u32(m4emu.STACK_TOP,DESC);m.u32(m4emu.STACK_TOP+4,OUT)
                    result=m.call(0x28df5198,APP,PRESET,3,0)
                elif outer=='replace':result=m.call(0x28dfcc48,APP,12,DESC,1)
                else:
                    for a,n in [(0x28dfd15c,0x370),(0x28dfff4c,0x1dc)]:m.load(a,read(a,n))
                    action=OUT;m.u8(action+4,1);m.u8(action+8,0);m.u8(action+12,3);m.u32(action+16,0);m.write(action+24,read(descriptor_address,0x30))
                    m.u8(PRESET+0x64ac,1);m.u8(PRESET+0x64ae,1)
                    def locate(x):x.u32(x.reg('r2'),12 if outer=='preset_existing' else -1);x.reg('r0',0)
                    stub(0x28dffef8,locate);stub(0x28dfae0c,lambda x:(x.u8(x.stack_args(1)[0],1),x.reg('r0',0)))
                    result=m.call(0x28dfd15c,APP,action,0)

                assert len(creates)==2,(outer,creates)
                assert s(result)==error
                calls=[hex(a) for a,_ in m.log]
                if outer in ['insert','preset_new']:assert m.u32(NEW+0x24)&1==0 and m.u32(META+36+4*13)==0
                if outer in ['replace','preset_existing']:
                    assert m.u32(OLD+0x24)&3==3 and m.u32(OLD+0x9f0)==SLOT
                    assert m.u32(SLOT+4)==OLD
                    assert len(m.calls(0x28df4cd8))==1 and m.calls(0x28df4cd8)[0][2]==0
                report['cases'].append({'case':outer,'descriptor_address':hex(descriptor_address),'injected_second_graph_create_status':error,'status':s(result),'create_calls':[[hex(v) for v in row] for row in creates],'calls':calls,'old_flags':m.u32(OLD+0x24),'new_flags':m.u32(NEW+0x24),'slot_object':hex(m.u32(SLOT+4)),'old_slot':hex(m.u32(OLD+0x9f0)),'new_slot':hex(m.u32(NEW+0x9f0))})
    # Execute real receive-loop discriminator and matching pending-status handler.
    for token in [-2,42]:
        for status in [0,-19,-31107]:
            m,stub=fresh()
            for a,n in [(0x28da7adc,0x10c),(0x28da6dc0,0xc0)]:m.load(a,read(a,n))
            owner=0x281d3448;vt=OUT;pending=CTX;task=MODEL;receive=0x28f10080
            m.u32(owner+16,vt);m.u32(vt+56,receive|1);m.u32(owner+0x478,pending);m.u32(owner+0x24c,0)
            m.u32(pending,0x12345678);m.u32(pending+4,42);m.u32(pending+8,0);m.u32(pending+12,0);m.u32(pending+28,0)
            def rx(x):
                msg=x.reg('r1');x.u32(msg,token);x.u32(msg+4,status);x.u32(task+12,0);x.reg('r0',1)
            stub(receive,rx)
            for a in [0x28e24a90,0x28e24960,0x28e249a8]:stub(a)
            result=m.call(0x28da7adc,task)
            actual=m.u32(pending)
            assert actual==(0x12345678 if token==-2 else status&0xffffffff)
            report['cases'].append({'case':'receive_loop','message_token':token,'message_status':status,'pending_status':s(actual),'pending_status_changed':token!=-2,'native_dispatch_handler_entered':bool(m.calls(0x28e24960))})
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hxf', type=Path, help='Unmodified HX Stomp 3.80.0 HXF')
    args = parser.parse_args()
    print(json.dumps(trace(args.hxf), indent=2))


if __name__ == '__main__':
    main()
