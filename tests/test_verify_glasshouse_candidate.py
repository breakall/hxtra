"""Verify actual combined archives, not source-reassembled replacement callbacks."""
from copy import deepcopy
import hashlib
import os
import struct

import pytest

import kit_patch_amp as kit
import m4cache
import patch_click
import patch_comp
import patch_glasshouse_build as glasshouse
import patch_menu
import patch_microlooper_build as atmosphere
import verify_glasshouse_candidate as verify
from sharc import glasshouse_storage as storage
from sharc import microlooper_adapter as loader
from sharc import nam_multi
from sharc import sasm


@pytest.fixture(scope='module')
def candidate(tmp_path_factory):
    path=os.environ.get('HX_STOMP_HXF')
    if not path:pytest.skip('HX_STOMP_HXF is not set')
    base=m4cache.nam_base(path,str(tmp_path_factory.mktemp('glasshouse-verifier')))
    image,_=kit.load_l6ia_from_any(base)
    image,_=atmosphere.prepare_metadata(image,dsp_cost=2000,mono_dsp_cost=1700,log=lambda _:None)
    # These are structural test costs, not measured hardware admission charges.
    image,_=glasshouse.prepare_metadata(image,dsp_cost=4000,mono_dsp_cost=3000,log=lambda _:None)
    entries,_=patch_menu.menu_entries(lambda n:kit.get_entry_swapped(image,n),
        env={'HX_MICRO_LOOPER':'1','HX_LONG_PRESS':'1','HX_GR':'1','HX_CLICK':'1'})
    image,_,_=kit.l6ia.rebuild_archive(image,entries)
    with nam_multi.flags(['--mid-sweep']):source,layout=nam_multi.build(2)
    image,_=kit.patch_kernel(image,source,'nam2.asm',relocate=False,log=lambda _:None)
    image,_=patch_click.add_click(image,log=lambda _:None,lay=layout)
    image=patch_comp.patch_comp(image,log=lambda _:None)
    image=patch_comp.patch_dsp(image,log=lambda _:None,lay=layout)
    image,_=atmosphere.link_dsp(image,log=lambda _:None)
    return glasshouse.link_dsp(image,log=lambda _:None)


def changed_word(candidate,address):
    """Change one actual normal32 loader word and repair outer integrity only."""
    image,report=candidate
    raw=kit.l6ia.swap32(kit.get_entry_swapped(image,2))
    words=list(struct.unpack(f'<{len(raw)//4}I',raw));at=384;target=None
    for tag,count,base,payload in loader.ldr_blocks(raw):
        if tag==4 and base<=address<base+count:
            target=at+3+address-base
        at+=3+len(payload)
    assert target is not None,'mutation must hit a real initialized candidate word'
    words[target]^=1
    raw=struct.pack(f'<{len(words)}I',*words)
    image,_,_=kit.l6ia.rebuild_archive(image,{2:kit.l6ia.swap32(raw)})
    report=deepcopy(report);report['candidate_archive_sha256']=hashlib.sha256(image).hexdigest()
    return image,report


@pytest.mark.firmware
def test_actual_combined_candidate_executes_native_callbacks_and_audio(candidate):
    image,report=candidate
    result=verify.verify_archive(image,report)
    assert result['allocation_verified_offline'] and result['native_callbacks_executed']
    assert result['native_member_allocator_executed']
    assert result['audio_verified_offline']
    assert result['boot_transport']['emitted_decoder_executed']
    assert result['boot_transport']['decoded_memory_identical']
    assert result['entry2_remaining_bytes']>0
    assert result['audio']['instruction_counts_are_hardware_cycles'] is False
    assert len(result['audio']['models'])==2
    assert all(row['cases']==12 and row['frames']==768 for row in result['audio']['models'])
    assert not result['hardware_boot_verified'] and not result['hardware_dsp_cost_verified']


@pytest.mark.firmware
@pytest.mark.parametrize('mutation,message',[
    ('fingerprint','fingerprint'),('partition','partition binding'),
    ('identity','identity/allocation'),('parameter','declaration'),('cost','cost'),
    ('callback','process_entry|report callbacks'),('aliases','ISA aliases'),('overlap','overlap'),
])
def test_report_cannot_override_candidate_contract(candidate,mutation,message):
    image,original=candidate;report=deepcopy(original)
    if mutation=='fingerprint':report['candidate_archive_sha256']='0'*64
    if mutation=='partition':report['entry2_remaining_bytes']+=4
    if mutation=='identity':report['models'][0]['private_dm_words']-=1
    if mutation=='parameter':report['models'][0]['effect']['parameters'][0]['default']=0.
    if mutation=='cost':report['models'][0]['declared_dsp_cost']+=1
    if mutation=='callback':report['models'][0]['process_entry']+=1
    if mutation=='aliases':report['executable_sections'][1]['data_begin']-=3
    if mutation=='overlap':report['executable_sections'][1]=deepcopy(report['executable_sections'][0])
    with pytest.raises(ValueError,match=message):verify.verify_archive(image,report,audio_check=False)


@pytest.mark.firmware
@pytest.mark.parametrize('owner,message',[
    ('core','emitted executable'),('registry','native registry'),('transport','fingerprint'),
])
def test_repaired_archive_checksums_do_not_hide_modified_code_or_transport(candidate,owner,message):
    _,report=candidate
    address={'core':report['pm_base']*3//2,
             'registry':report['models'][0]['registry_address']+5,
             'transport':storage.TABLE+storage.HEADER_WORDS+4}[owner]
    image,changed=changed_word(candidate,address)
    with pytest.raises(ValueError,match=message):verify.verify_archive(image,changed,audio_check=False)


@pytest.mark.firmware
def test_audio_harness_cannot_replace_candidate_instructions_with_assembled_source(candidate,monkeypatch):
    image,report=candidate
    raw=kit.l6ia.swap32(kit.get_entry_swapped(image,2));expanded=storage.expand(raw)
    decoded=verify.verify_code(expanded,report)
    entry=report['models'][0]['process_entry']
    section,_=sasm.assemble(f'.section pm {entry:#x}\nJUMP 0x8ea4f;\n','mutated-candidate.asm')
    decoded[entry]=section[0].words[0]
    configs=list(verify.configurations())
    monkeypatch.setattr(verify,'configurations',lambda:iter(configs[:1]))
    with pytest.raises(ValueError,match='left verified code'):
        verify.verify_audio(expanded,decoded,report)


@pytest.mark.firmware
@pytest.mark.parametrize('field',[
    'preset_id','primitive','declared_dsp_cost','private_dm_words','private_pm_words',
    'private_sdram_words','process_entry','init_entry','control_entry',
])
def test_root_summary_must_match_the_verified_model(candidate,field):
    image,original=candidate;report=deepcopy(original);report[field]+=1
    with pytest.raises(ValueError,match='root '+field):verify.verify_archive(image,report,audio_check=False)


@pytest.mark.firmware
@pytest.mark.parametrize('field,message',[
    ('callback_instructions','callback size'),('code_storage','code_storage'),
    ('permanent_reservation','permanent_reservation'),('role','roles/extent'),
])
def test_resource_summary_cannot_override_assembled_code_ownership(candidate,field,message):
    image,original=candidate;report=deepcopy(original)
    if field=='callback_instructions':report[field]+=2
    elif field=='role':report['executable_sections'][1]['role']='startup_decoder'
    else:report[field]['instructions']+=2
    with pytest.raises(ValueError,match=message):verify.verify_archive(image,report,audio_check=False)
