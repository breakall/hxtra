"""The diagnostic host accepts one coherent versioned record, without edits."""
import json
import struct
from types import SimpleNamespace

import pytest

import hx_microlooper_probe as host
from sharc import microlooper_adapter as adapter
import usb_commands


def reply(*, valid=1, sequence=2, received=100, now=200, payload=None):
    payload = [adapter.MAGIC, 17] + list(range(14)) if payload is None else payload
    if not valid:
        sequence = received = 0
        payload = [0] * 16
    age = (now - received) & 0xffffffff if valid else 0
    return struct.pack('<24I', host.MAGIC, 96, valid, sequence, received, now, age, 0, *payload)


@pytest.mark.parametrize('received,now,age', [(100, 200, 100), (0xfffffff0, 20, 36), (0, 0, 0)])
def test_fresh_context_and_clock_wrap(received, now, age):
    out = host.decode_reply(reply(received=received, now=now))
    assert out['valid'] and out['status'] == 'fresh' and out['age_us'] == age
    assert out['context']['calls'] == 17
    assert not out['native_stereo_abi_verified']


def test_freshness_boundary_stale_and_zero_source_sequence():
    blob = reply(sequence=0, received=5, now=105)
    assert host.decode_reply(blob, max_age_us=100)['status'] == 'fresh'
    out = host.decode_reply(blob, max_age_us=99)
    assert out['status'] == 'stale' and out['source_sequence'] == 0 and out['context']


def test_no_data_is_explicit_and_keeps_only_current_clock():
    out = host.decode_reply(reply(valid=0, now=0x12345678))
    assert not out['valid'] and out['context'] is None and out['status'] == 'no_data'
    assert out['now_us'] == 0x12345678 and out['age_us'] == 0


@pytest.mark.parametrize('index,value', [(0, 0), (1, 95), (2, 2), (3, 3), (6, 1), (7, 1), (8, 0)])
def test_reject_corrupt_header_sequence_age_and_context(index, value):
    words = list(struct.unpack('<24I', reply()))
    words[index] = value
    with pytest.raises(ValueError):
        host.decode_reply(struct.pack('<24I', *words))


@pytest.mark.parametrize('index', [3, 4, 6, 8, 23])
def test_no_data_cannot_hide_nonzero_metadata_or_payload(index):
    words = list(struct.unpack('<24I', reply(valid=0)))
    words[index] = 1
    with pytest.raises(ValueError, match='no-data'):
        host.decode_reply(struct.pack('<24I', *words))


@pytest.mark.parametrize('blob', [None, {}, [], b'', b'x' * 95, b'x' * 97])
def test_reject_nonbinary_or_wrong_length_reply(blob):
    with pytest.raises(ValueError, match='96 bytes'):
        host.decode_reply(blob)


@pytest.mark.parametrize('age', [-1, 0x80000000, True, 1.5])
def test_reject_invalid_age_limit(age):
    with pytest.raises(ValueError, match='maximum age'):
        host.decode_reply(reply(), max_age_us=age)


def test_request_uses_reserved_command_without_parameters():
    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return reply()
    result = host.read_context(SimpleNamespace(ed=SimpleNamespace(request=request)), timeout=2.5)
    assert calls == [((usb_commands.DIAGNOSTIC_CONTEXT,), {'timeout': 2.5})]
    assert result['status'] == 'fresh'


def test_offline_cli_decodes_saved_result(tmp_path, capsys):
    path = tmp_path / 'context.bin'
    path.write_bytes(reply(now=2000))
    host.main(['--reply', str(path), '--max-age-ms', '1'])
    assert json.loads(capsys.readouterr().out)['status'] == 'stale'


@pytest.mark.parametrize('age', ['-1', '2147484'])
def test_cli_rejects_invalid_threshold_before_opening_usb(age):
    with pytest.raises(SystemExit) as exc:
        host.main(['--max-age-ms', age])
    assert exc.value.code == 2
