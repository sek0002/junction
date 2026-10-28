"""Annotated GenBank files for a validated, private build list."""
import io
import re
from zipfile import ZIP_DEFLATED, ZipFile

from .exports import genbank_bytes


def build_genbank_zip(builds):
    """Keep every product in its own file; numbered names avoid collisions."""
    output = io.BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for index, (build_id, request, result) in enumerate(builds, 1):
            name = re.sub(r'[^A-Za-z0-9_.-]+', '_', request.name).strip('._')[:90] or 'assembly'
            archive.writestr(f'{index:03d}_{name}.gb', genbank_bytes(
                request.name, result['sequence'], result.get('features'), result['circular'],
                notes=[f'Assembly enzyme: {request.enzyme}', f'Build list entry: {build_id}'],
            ))
    return output.getvalue()
