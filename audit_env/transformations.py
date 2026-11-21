"""Versioned bijective ID renaming and benign business/order transformations.

Only declared ID fields are rewritten. Rates, dates, monetary values, posting
sequences and currencies are fixed. FX evidence keys retain their published
date/currency identity; settlement IDs follow their remapped payment IDs.
"""

from __future__ import annotations

import hashlib
import json
import random

from .generation import GeneratedEpisode


TRANSFORM_VERSION = "stage10-transform-v1"
TABLES = ("ledger", "invoices", "payments", "fx")


def _rng(seed, stream):
    if type(seed) is not int:
        raise ValueError("transformation seed must be an integer")
    digest = hashlib.sha256(f"{TRANSFORM_VERSION}:{seed}:{stream}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _id_field(key):
    return key == "id" or key.endswith("_id") or key.endswith("_ids") or key == "evidence_sets"


def _visit(value, key="", *, on_id, on_description=lambda text: text):
    if isinstance(value, dict):
        return {name: _visit(item, name, on_id=on_id, on_description=on_description)
                for name, item in value.items()}
    if isinstance(value, list):
        return [_visit(item, key, on_id=on_id, on_description=on_description) for item in value]
    if isinstance(value, str):
        if key in ("clean_value", "observed_value") and value.startswith("{"):
            # Provenance embeds complete ledger records as JSON strings.
            record = json.loads(value)
            return json.dumps(_visit(record, on_id=on_id, on_description=on_description),
                              ensure_ascii=False, separators=(",", ":"))
        if _id_field(key):
            return on_id(value)
        if key == "description":
            return on_description(value)
    return value


def id_mapping(episode: GeneratedEpisode, seed: int) -> dict[str, str]:
    """A deterministic permutation into a fresh opaque namespace, including private IDs."""
    ids = set()
    _visit(episode.model_dump(mode="json"), on_id=lambda value: ids.add(value) or value)
    for public in (episode.public, episode.clean):
        ids.update(row.evidence_id for row in public.fx)
        ids.update(f"settlement:{p.payment_id}" for p in public.payments)
    rng = _rng(seed, "ids")
    mapping = {value: value for value in sorted(ids) if value.startswith("fx:")}
    used = set(ids)
    for value in sorted(ids):
        if value.startswith(("settlement:", "fx:")):
            continue
        while True:
            replacement = f"id-{rng.getrandbits(128):032x}"
            if replacement not in used:
                break
        used.add(replacement)
        mapping[value] = replacement
    for value in sorted(ids):
        if value.startswith("settlement:"):
            mapping[value] = "settlement:" + mapping[value.removeprefix("settlement:")]
    validate_mapping(mapping)
    return mapping


def validate_mapping(mapping):
    if (not isinstance(mapping, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                                             for k, v in mapping.items())
            or len(set(mapping.values())) != len(mapping)):
        raise ValueError("ID mapping must be a bijection")
    for old, new in mapping.items():
        if old.startswith("fx:") and old != new:
            raise ValueError("FX evidence keys are derived from unchanged dates and currencies")
        if old.startswith("settlement:"):
            payment = old.removeprefix("settlement:")
            if payment not in mapping or new != "settlement:" + mapping[payment]:
                raise ValueError("settlement ID must follow its payment")


def remap_ids(value, mapping):
    """Rewrite JSON actions, observations, summaries and serialized private records."""
    validate_mapping(mapping)
    return _visit(value, on_id=lambda item: mapping.get(item, item))


def transform_episode(episode: GeneratedEpisode, seed: int, *, mapping=None, rename=True, reorder=True):
    """Return an independent transformed episode and its complete ID map."""
    mapping = id_mapping(episode, seed) if mapping is None else dict(mapping)
    expected = set(id_mapping(episode, seed))
    validate_mapping(mapping)
    if set(mapping) != expected:
        raise ValueError("mapping must cover every episode and evidence ID")

    def description(text):
        if not rename:
            return text
        rng = _rng(seed, "description:" + text)
        return f"Synthetic {rng.choice(('Cedar', 'Willow', 'Amber', 'Maple'))} service {rng.getrandbits(64):016x}"

    data = _visit(episode.model_dump(mode="json"), on_id=lambda item: mapping[item],
                  on_description=description)
    if reorder:
        for section in ("public", "clean"):
            for table in TABLES:
                _rng(seed, section + ":" + table).shuffle(data[section][table])
    result = GeneratedEpisode.model_validate_json(json.dumps(data))
    return result, mapping
