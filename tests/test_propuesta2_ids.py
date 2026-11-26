"""Exercise the browser transport with integers that cannot round-trip as doubles."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_transport_preserves_large_ids_and_quoted_user_text():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the JavaScript transport test")
    module = Path(__file__).resolve().parents[1] / "app/static/propuesta2/api.js"
    script = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1]);
const {decode, encode} = await import('data:text/javascript;base64,' + source.toString('base64'));
const id = '9223372036854775807';
const note = 'A literal "deck_id":9007199254740993 and a backslash ' + String.fromCharCode(92);
const raw = '[{"id":' + id + ',"card_id":null,"front":' + JSON.stringify(note) + ',"quality":4}]';
assert.deepEqual(decode(raw), [{id, card_id:null, front:note, quality:4}]);
assert.equal(encode({deck_id:id, text:note}),
    '{"deck_id":' + id + ',"text":' + JSON.stringify(note) + '}');
assert.throws(() => encode({deck_id:Number(id)}));
assert.throws(() => encode({deck_id:'1,"quality":5'}));
"""
    subprocess.run([node, "--input-type=module", "-e", script, str(module)], check=True)
