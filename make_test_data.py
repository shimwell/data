#!/usr/bin/env python3

"""
Download ENDF/B-VII.1 ENDF and ACE files from NNDC and WMP files from GitHub and
generate a full HDF5 library with incident neutron, incident photon, thermal
scattering data, and windowed multipole data. This data is used for OpenMC's
regression test suite.
"""

import glob
import os
from pathlib import Path
import tarfile
import tempfile
from urllib.parse import urljoin
import zipfile

import openmc.data

from utils import download

base_ace = 'http://www.nndc.bnl.gov/endf-b7.1/aceFiles/'
base_endf = 'http://www.nndc.bnl.gov/endf-b7.1/zips/'
base_wmp = 'https://github.com/mit-crpg/WMP_Library/releases/download/v1.1/'
files = [
    (base_ace, 'ENDF-B-VII.1-neutron-293.6K.tar.gz', '9729a17eb62b75f285d8a7628ace1449'),
    (base_ace, 'ENDF-B-VII.1-tsl.tar.gz', 'e17d827c92940a30f22f096d910ea186'),
    (base_endf, 'ENDF-B-VII.1-neutrons.zip', 'e5d7f441fc4c92893322c24d1725e29c'),
    (base_endf, 'ENDF-B-VII.1-photoat.zip', '5192f94e61f0b385cf536f448ffab4a4'),
    (base_endf, 'ENDF-B-VII.1-atomic_relax.zip', 'fddb6035e7f2b6931e51a58fc754bd10'),
    (base_wmp, 'WMP_Library_v1.1.tar.gz', '8523895928dd6ba63fba803e3a45d4f3')
]


def fix_zaid(table, old, new):
    filename = os.path.join('tsl', table)
    with open(filename, 'r') as fh:
        text = fh.read()
    text = text.replace(old, new, 1)
    with open(filename, 'w') as fh:
        fh.write(text)


pwd = Path.cwd()
output_dir = pwd / 'nndc_hdf5'
os.makedirs('nndc_hdf5/photon', exist_ok=True)

with tempfile.TemporaryDirectory() as tmpdir:
    # Temporarily change dir
    os.chdir(tmpdir)

    # =========================================================================
    # Download files from NNDC server
    for base, fname, checksum in files:
        download(urljoin(base, fname), checksum)

    # =========================================================================
    # EXTRACT FILES FROM TGZ

    for _, f, _ in files:
        print('Extracting {}...'.format(f))
        path = Path(f)
        if path.suffix == '.gz':
            with tarfile.open(f, 'r') as tgz:
                if 'tsl' in f:
                    tgz.extractall(path='tsl')
                else:
                    tgz.extractall()
        elif path.suffix == '.zip':
            zipfile.ZipFile(f).extractall()

    # =========================================================================
    # FIX ZAID ASSIGNMENTS FOR VARIOUS S(A,B) TABLES

    print('Fixing ZAIDs for S(a,b) tables')
    fix_zaid('bebeo.acer', '8016', '   0')
    fix_zaid('obeo.acer', '4009', '   0')

    library = openmc.data.DataLibrary()

    # =========================================================================
    # INCIDENT NEUTRON DATA

    neutron_files = sorted(glob.glob('ENDF-B-VII.1-neutron-293.6K/*.ace'))
    for f in neutron_files:
        print('Converting {}...'.format(os.path.basename(f)))
        data = openmc.data.IncidentNeutron.from_ace(f)

        # Check for fission energy release data on MF=1, MT=458
        endf_filename = 'neutrons/n-{:03}_{}_{:03}{}.endf'.format(
            data.atomic_number,
            data.atomic_symbol,
            data.mass_number,
            'm{}'.format(data.metastable) if data.metastable else ''
        )
        ev = openmc.data.endf.Evaluation(endf_filename)
        if (1, 458) in ev.section:
            endf_data = openmc.data.IncidentNeutron.from_endf(ev)
            data.fission_energy = endf_data.fission_energy

        # Add 0K elastic scattering data for select nuclides
        if data.name in ('U235', 'U238', 'Pu239'):
            data.add_elastic_0K_from_endf(endf_filename)

        # Determine filename
        outfile = output_dir / (data.name + '.h5')
        data.export_to_hdf5(outfile, 'w', 'earliest')

        # Register with library
        library.register_file(outfile)

    # =========================================================================
    # THERMAL SCATTERING DATA

    thermal_files = sorted(glob.glob('tsl/*.acer'))
    for f in thermal_files:
        print('Converting {}...'.format(os.path.basename(f)))
        data = openmc.data.ThermalScattering.from_ace(f)

        # Determine filename
        outfile = output_dir / (data.name + '.h5')
        data.export_to_hdf5(outfile, 'w', 'earliest')

        # Register with library
        library.register_file(outfile)

    # =========================================================================
    # INCIDENT PHOTON DATA

    for z in range(1, 101):
        element = openmc.data.ATOMIC_SYMBOL[z]
        print('Generating HDF5 file for Z={} ({})...'.format(z, element))

        # Generate instance of IncidentPhoton
        photo_file = Path('photoat') / 'photoat-{:03}_{}_000.endf'.format(z, element)
        atom_file = Path('atomic_relax') / 'atom-{:03}_{}_000.endf'.format(z, element)
        data = openmc.data.IncidentPhoton.from_endf(photo_file, atom_file)

        # Write HDF5 file and register it
        outfile = output_dir / 'photon' / (element + '.h5')
        data.export_to_hdf5(outfile, 'w', 'earliest')
        library.register_file(outfile)

    # =========================================================================
    # WINDOWED MULTIPOLE DATA

    # Move data into output directory
    os.rename('WMP_Library', str(output_dir / 'wmp'))

    # Add multipole data to library
    for f in sorted(glob.glob('{}/wmp/*.h5'.format(output_dir))):
        print('Registering WMP file {}...'.format(f))
        library.register_file(f)

    library.export_to_xml(output_dir / 'cross_sections.xml')

    # =========================================================================
    # CREATE TARBALL AND MOVE BACK

    print('Creating compressed archive...')
    test_tar = pwd / 'nndc_hdf5_test.tar.xz'
    with tarfile.open(str(test_tar), 'w:xz') as txz:
        txz.add(output_dir)

    # Change back to original directory
    os.chdir(str(pwd))
