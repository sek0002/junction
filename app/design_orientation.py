"""Orient existing donors by their context; unflanked insert DNA stays as entered."""
from .sequence_engine import _oriented_chain, fragment_orientations


def orient_fragments(entries, enzyme, backbone=None, left='', right=''):
    chosen, index = {}, 0
    while index < len(entries):
        if entries[index]['kind'] != 'fragment':
            index += 1
            continue
        start = index
        while index < len(entries) and entries[index]['kind'] == 'fragment':
            index += 1
        options = []
        for entry in entries[start:index]:
            variants = fragment_orientations(entry['sequence'], enzyme)
            options.append([variant for variant in variants if variant['valid']] or variants)
        required_left = (backbone['right_overhang'] if backbone else left) if start == 0 else None
        required_right = (backbone['left_overhang'] if backbone else right) if index == len(entries) else None
        circular = None if start == 0 and index == len(entries) and not backbone else False
        resolved = _oriented_chain(options, circular, required_left or None, required_right or None)
        chosen.update(zip(range(start,index),resolved))
    return chosen


def annotate_orientations(assembly, nodes):
    """The map records orientation relative to the original library molecule."""
    sources = {node.get('fragment_id'): node for node in nodes if node['kind'] == 'fragment'}
    for feature in assembly['features']:
        node = sources.get(feature.get('fragment_id')) if feature.get('source') == 'fragment' else None
        if node is not None:
            reverse = bool(node['reverse'])
            feature.update(strand=-1 if reverse else 1, reverse_complement=reverse)
            if reverse:
                feature['qualifiers'] = dict(feature.get('qualifiers') or {}) | {'note':['Automatically reverse-complemented from the library fragment.']}
    return assembly
