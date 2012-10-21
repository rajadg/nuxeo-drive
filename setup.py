#! /usr/bin/env python
#
# Copyright (C) 2012 Nuxeo
#

import sys
from datetime import datetime

from distutils.core import setup
scripts = ["nuxeo-drive-client/bin/ndrive"]
freeze_options = {}

name = 'nuxeo-drive'
packages = [
    'nxdrive',
    'nxdrive.tests',
    'nxdrive.gui',
    'nxdrive.data',
]
script = 'nuxeo-drive-client/bin/ndrive'
icon = 'nuxeo-drive-client/nxdrive/data/nuxeo_drive_icon_64.ico'
version = '0.1.0'

if '--dev' in sys.argv:
    # timestamp the dev artifacts for continuous integration
    # distutils only accepts "b" + digit
    sys.argv.remove('--dev')
    timestamp = datetime.utcnow().isoformat()
    timestamp = timestamp.replace(":", "")
    timestamp = timestamp.replace(".", "")
    timestamp = timestamp.replace("T", "")
    timestamp = timestamp.replace("-", "")
    version += "b" + timestamp


if '--freeze' in sys.argv:
    print "Building standalone executable..."
    sys.argv.remove('--freeze')
    from cx_Freeze import setup, Executable
    from cx_Freeze.windist import bdist_msi  # monkeypatch to add options

    # build_exe does not seem to take the package_dir info into account
    sys.path.append('nuxeo-drive-client')

    executables = [Executable(script, base=None, icon=icon)]
    if sys.platform == "win32":
        # Windows GUI program that can be launched without a cmd console
        executables.append(
            Executable(script, targetName="ndrivew.exe", base="Win32GUI",
                       icon=icon))
    scripts = []
    freeze_options = dict(
        executables=executables,
        options={
            "build_exe": {
                "includes": [
                    "PySide",
                    "PySide.QtCore",
                    "PySide.QtNetwork",
                    "PySide.QtGui",
                    "atexit",  # implicitly required by PySide
                    "sqlalchemy.dialects.sqlite",
                ],
                "packages": packages + [
                    "nose",
                ],
                "excludes": [
                    "ipdb",
                    "clf",
                    "IronPython",
                    "pydoc",
                    "tkinter",
                ],
            },
            "bdist_msi": {
                "add_to_path": True,
                "upgrade_code": '{800B7778-1B71-11E2-9D65-A0FD6088709B}',
            },
        },
    )
    # TODO: investigate with esky to get an auto-updateable version but
    # then make sure that we can still have .msi and .dmg packages
    # instead of simple zip files.


setup(
    name=name,
    version=version,
    description="Desktop synchronization client for Nuxeo.",
    author="Olivier Grisel",
    author_email="ogrisel@nuxeo.com",
    url='http://github.com/nuxeo/nuxeo-drive',
    packages=packages,
    package_dir={'nxdrive': 'nuxeo-drive-client/nxdrive'},
    package_data={'nxdrive.data': ['*.png', '*.svg', '*.ico']},
    scripts=scripts,
    long_description=open('README.rst').read(),
    **freeze_options
)
