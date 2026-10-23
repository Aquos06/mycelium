"""mycelium SDK: the one library every module and core service shares.

- bus:       Bus interface, NatsBus (real) and InMemoryBus (tests)
- kv:        KV interface, NatsKV (JetStream KV) and InMemoryKV (tests)
- envelope:  id / ts / source / cause / hops for every published message
- manifest:  module manifest schema + validation
- module:    Module base runtime (subscribe, answer requests, emit, observe, intervals)
- subjects:  subject naming helpers and wildcard matching
- validation: one formatter for pydantic errors in rpc replies
"""

from .bus import Bus, InMemoryBus, Message, NatsBus, Payload
from .envelope import Envelope, new_id, now_iso
from .kv import KV, InMemoryKV, NatsKV, kv_key
from .manifest import Manifest, ManifestError, load_manifest, validate_manifest
from .module import Module
from .subjects import subject_matches
from .validation import validation_message

__all__ = [
    "Bus",
    "InMemoryBus",
    "NatsBus",
    "Message",
    "Payload",
    "KV",
    "InMemoryKV",
    "NatsKV",
    "kv_key",
    "Envelope",
    "new_id",
    "now_iso",
    "Manifest",
    "ManifestError",
    "load_manifest",
    "validate_manifest",
    "Module",
    "subject_matches",
    "validation_message",
]
