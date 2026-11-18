"""Actual stock constructor prefix; synthetic arena context is never hidden."""
import os

import pytest

import kit_patch_amp as kit
import microlooper_allocation as allocation


@pytest.fixture(scope='module')
def entry2():
    stock=os.environ.get('HX_STOMP_HXF')
    if not stock:pytest.skip('HX_STOMP_HXF is not set')
    image,_=kit.load_l6ia_from_any(stock)
    entry=kit.l6ia.parse(image)[2]
    return image[entry['payload_off']:entry['payload_off']+entry['payload_len']]


@pytest.mark.firmware
@pytest.mark.parametrize('dm_words,pm_words,sdram_words',[(163,0,48000),(163,0,24000),(163,1,48000),
                                                       (145,13,1024),(0,0,0),(930,0,48000)])
def test_native_member_sizes_advance_parent_and_bound_child_descriptor(entry2,dm_words,pm_words,sdram_words):
    report=allocation.inspect_member_arenas(entry2,dm_words=dm_words,pm_words=pm_words,sdram_words=sdram_words)
    assert report['complete_prefix'],report
    assert report['member_count_reads']=={'dm_field13':True,'pm_field14':True,'sdram_field15':True}
    assert report['member_tail_setup_addresses']==[0x177f54,0x177f56,0x177f58]
    assert report['member_tail_i8']==0xb5000+20
    assert report['dm_descriptor_begin_end_current']==[0xb3000,0xb3000+dm_words,0xb3000]
    assert report['pm_descriptor_begin_end']==[0xe1000,0xe1000+pm_words]
    assert report['sdram_descriptor_begin_end']==[0x400000,0x400000+sdram_words]
    assert report['parent_pm_current']==0xe1000+pm_words
    assert report['parent_dm_current']==0xb3000+dm_words
    assert report['parent_sdram_current']==0x400000+sdram_words
    assert {address for _,address,_ in report['writes']}==(
        {0xb4002,0xb4005,0xb4008,0xc6fff,0xc7000} | set(range(0xb6000,0xb6000+27)))
    assert report['memory_guards_intact']
    assert report['synthetic_context']
    assert report['private_dm_allocation_executed'] and report['private_dm_extent_assigned']
    assert report['descriptor_copy_executed']


@pytest.mark.firmware
@pytest.mark.parametrize('kwargs,pm_done',[({'dm_words':1025},False),({'pm_words':257},False),
    ({'sdram_end':0x400000+47999},True),({'sdram_end':0x400000},True)])
def test_native_bounds_branch_rejects_exhaustion_before_descriptor_end_write(entry2,kwargs,pm_done):
    report=allocation.inspect_member_arenas(entry2,**kwargs)
    assert report['stop_address']==allocation.FAILURE
    assert report['stop_reason']=='arena exhausted'
    assert not report['complete_prefix']
    assert report['sdram_descriptor_begin_end']==[0x400000,kwargs.get('sdram_end',0x463000)]
    assert report['parent_sdram_current']==0x400000
    assert report['member_count_reads']['sdram_field15']==pm_done


@pytest.mark.firmware
def test_exact_arena_boundary_is_accepted(entry2):
    report=allocation.inspect_member_arenas(entry2,dm_end=0xb3000+163,
                                          pm_end=0xe1000,sdram_end=0x400000+48000)
    assert report['complete_prefix']
    assert report['sdram_descriptor_begin_end'][1]==0x400000+48000


@pytest.mark.firmware
def test_original_constructor_selects_member_records_from_composite_header(entry2):
    report=allocation.inspect_constructor_member_source(entry2)
    assert report['member_array_selection_verified']


@pytest.mark.firmware
def test_native_sdram_alignment_precedes_descriptor_copy_and_carving(entry2):
    report=allocation.inspect_member_arenas(entry2,sdram_begin=0x400001)
    assert report['complete_prefix']
    assert report['sdram_descriptor_begin_end']==[0x400400,0x400400+48000]
    assert report['parent_sdram_current']==0x400400+48000
    assert report['descriptor_copy_executed'] and report['memory_guards_intact']


@pytest.mark.firmware
@pytest.mark.parametrize('pm_words',[0,13])
@pytest.mark.parametrize('dm_begin',[0xb3000,0xb3400])
def test_native_allocated_private_base_reaches_process_i0(entry2,pm_words,dm_begin):
    report=allocation.inspect_process_private_binding(entry2,pm_words=pm_words,
                                                      dm_begin=dm_begin,dm_end=dm_begin+930)
    assert report['descriptor_copy_executed'] and report['complete_prefix']
    assert report['process_record_descriptor']==0xb6000
    assert report['process_record_private_dm']==dm_begin
    assert report['process_record_pm']==(0xe1000 if pm_words else 0)
    assert report['process_entry_registers']=={'i0':dm_begin,'i1':0xba000,'i2':0xbb000,
                                               'i3':0xb8000,'i8':0xe1000 if pm_words else 0}
    assert report['process_i0_verified']
    assert report['process_dispatch_addresses']==list(range(0x8cb37,0x8cb40))


@pytest.mark.firmware
def test_binding_refuses_rejected_allocation(entry2):
    with pytest.raises(ValueError,match='successful member allocation'):
        allocation.inspect_process_private_binding(entry2,dm_end=0xb3000+162)


def test_invalid_unsigned_context_is_rejected():
    for value in (-1,2**32,1.5):
        with pytest.raises(ValueError,match='unsigned32'):
            allocation.inspect_member_arenas(b'',sdram_words=value)
