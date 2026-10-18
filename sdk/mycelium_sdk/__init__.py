"""mycelium SDK: the one library every module and core service shares.

- bus:       Bus interface, NatsBus (real) and InMemoryBus (tests)
- manifest:  module manifest schema + validation
- module:    Module base runtime (subscribe, answer requests, emit, observe, intervals)
- subjects:  subject naming helpers and wildcard matching
"""

from .bus import Bus, InMemoryBus, Message, NatsBus
from .manifest import Manifest, ManifestError, load_manifest, validate_manifest
from .module import Module
from .subjects import subject_matches

__all__ = [
    "Bus",
    "InMemoryBus",
    "NatsBus",
    "Message",
    "Manifest",
    "ManifestError",
    "load_manifest",
    "validate_manifest",
    "Module",
    "subject_matches",
]
