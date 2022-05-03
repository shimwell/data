#!/usr/bin/env python3

"""
Generate JEFF 3.3 HDF5 library for use in OpenMC by first processing ENDF files
using NJOY. The resulting library will contain incident neutron, photoatomic,
and thermal scattering data.
"""

import argparse
from multiprocessing import Pool
from pathlib import Path
from urllib.parse import urljoin

import openmc.data

from utils import download, extract, process_neutron, process_thermal


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawDescriptionHelpFormatter):
    pass


parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=CustomFormatter
)
parser.add_argument('-d', '--destination', type=Path, default=None,
                    help='Directory to create new library in')
parser.add_argument('--download', action='store_true',
                    help='Download zip files from NNDC')
parser.add_argument('--no-download', dest='download', action='store_false',
                    help='Do not download zip files from NNDC')
parser.add_argument('--extract', action='store_true',
                    help='Extract zip files')
parser.add_argument('--no-extract', dest='extract', action='store_false',
                    help='Do not extract zip files')
parser.add_argument('--libver', choices=['earliest', 'latest'],
                    default='earliest', help="Output HDF5 versioning. Use "
                    "'earliest' for backwards compatibility or 'latest' for "
                    "performance")
parser.add_argument('--temperatures', type=float,
                    default=[250.0, 293.6, 600.0, 900.0, 1200.0, 2500.0],
                    help="Temperatures in Kelvin", nargs='+')
parser.set_defaults(download=True, extract=True, tmpdir=True)
args = parser.parse_args()


library_name = 'jeff'
release = '33'

cwd = Path.cwd()

endf_files_dir = cwd.joinpath('-'.join([library_name, args.release, 'endf']))
neutron_dir = endf_files_dir
download_path = cwd.joinpath('-'.join([library_name, args.release, 'download']))


release_details = {
    '33': {
        'neutron': {
            'base_url': 'http://www.oecd-nea.org/dbdata/jeff/jeff33/downloads/',
            'compressed_files': ['JEFF33-n.tgz',
                                 'JEFF33-tsl.tgz'],
            'checksums': ['e540bbf95179257280c61acfa75c83de',
                          '82a6df4cb802aa4a09b95309f7861c54'],
            'file_type': 'endf',
            'endf_files': endf_files_dir.rglob('[aA-zZ]*.jeff33'),
            'compressed_file_size': 497,
            'uncompressed_file_size': 1200,
            'sab_files': [
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinCaH2.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinCH2.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinH2O.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinIce.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinMesitylene-PhaseII.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinOrthoH.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinParaH.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinToluene.jeff33'),
                (neutron_dir / '1-H-1g.jeff33', neutron_dir / 'tsl-HinZrH.jeff33'),
                (neutron_dir / '1-H-2g.jeff33', neutron_dir / 'tsl-DinD2O.jeff33'),
                (neutron_dir / '1-H-2g.jeff33', neutron_dir / 'tsl-DinOrthoD.jeff33'),
                (neutron_dir / '1-H-2g.jeff33', neutron_dir / 'tsl-DinParaD.jeff33'),
                (neutron_dir / '4-Be-9g.jeff33', neutron_dir / 'tsl-Be.jeff33'),
                (neutron_dir / '6-C-0g.jeff33', neutron_dir / 'tsl-Graphite.jeff33'),
                (neutron_dir / '8-O-16g.jeff33', neutron_dir / 'tsl-O16inAl2O3.jeff33'),
                (neutron_dir / '8-O-16g.jeff33', neutron_dir / 'tsl-OinD2O.jeff33'),
                (neutron_dir / '12-Mg-24g.jeff33', neutron_dir / 'tsl-Mg.jeff33'),
                (neutron_dir / '13-Al-27g.jeff33', neutron_dir / 'tsl-Al27inAl2O3.jeff33'),
                (neutron_dir / '14-Si-28g.jeff33', neutron_dir / 'tsl-Silicon.jeff33'),
                (neutron_dir / '20-Ca-40g.jeff33', neutron_dir / 'tsl-CainCaH2.jeff33'),
            ]
        }
    }
}


# neutron_dir = Path('JEFF33-tsl')




# =========================================================================
# DOWNLOAD FILES
if args.download:
    for f in release_details[release]['compressed_files']:
        # Establish connection to URL
        download(urljoin(release_details[args.release]['base_url'], f),
                 output_path=download_path)

# =========================================================================
# EXTRACT ARCHIVES
if args.extract:
    extract(
        compressed_files=release_details[release]['compressed_files'],
        extraction_dir=endf_files_dir
    )


# =========================================================================
# PROCESS INCIDENT NEUTRON AND THERMAL SCATTERING DATA IN PARALLEL
neutron_files = release_details[release]['neutron']['endf_files']

# Create output directory if it doesn't exist
args.destination.mkdir(parents=True, exist_ok=True)

with Pool() as pool:
    results = []
    for filename in sorted(neutron_files):

        func_args = (filename, args.destination, args.libver)
        r = pool.apply_async(process_neutron, func_args)
        results.append(r)

    for r in results:
        r.wait()


library = openmc.data.DataLibrary()

# Register with library
for p in sorted((args.destination).glob('*.h5')):
    library.register_file(p)

# Write cross_sections.xml
library.export_to_xml(args.destination / 'cross_sections.xml')
