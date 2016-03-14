#!/usr/bin/env pypy-c

import os
from setuptools import setup

rest = []
base = os.path.join(os.path.dirname(__file__), '_jitviewer')
for dirname, _, filenames in os.walk(os.path.join(base, 'static')):
    dirname = os.path.relpath(dirname, base)
    for x in filenames:
        rest.append(os.path.join(dirname, x))

setup(name='JitViewer',
      version='0.2',
      description="Viewer for pypy's jit traces",
      author='Maciej Fijalkowski, Antonio Cuni and the PyPy team',
      author_email='fijall@gmail.com',
      url='http://pypy.org',
      packages=['_jitviewer'],
      scripts=['bin/jitviewer.py', 'bin/qwebview.py'],
      install_requires=['flask', 'pygments', 'simplejson', 'Jinja2>=2.6'],
      include_package_data=True,
      package_data={'': ['templates/*.html'] + rest},
      zip_safe=False)
