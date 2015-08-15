# -*- coding: utf-8 -*-

# Copyright (C) 2015 Michael Hogg

# This file is part of pyvct - See LICENSE.txt for information on usage and redistribution

import pyvct

from distutils.core import setup
from distutils.extension import Extension
import numpy
try:
    from Cython.Distutils import build_ext
except ImportError:
    use_cython = False
else:
    use_cython = True
    
cmdclass    = {}
ext_modules = []
if use_cython:  
    ext_modules += [ Extension("pyvct.cythonMods", sources=["cython/cythonMods.pyx"],include_dirs=[numpy.get_include()],language="c++")]
    cmdclass.update({ 'build_ext':build_ext })
else:
    ext_modules += [ Extension("pyvct.cythonMods", sources=["cython/cythonMods.cpp"],include_dirs=[numpy.get_include()],language="c++")]
    
setup(
    name = 'pyvct',
    version = pyvct.__version__,
    description = 'ABAQUS plug-in to create virtual CTs from 3D finite element bone/implant models',
    license = 'MIT license',
    keywords = ["ABAQUS","plug-in","virtual","CT","finite","element","bone","python","cython"],
    author = 'Michael Hogg',
    author_email = 'michael.christopher.hogg@gmail.com',
    url = "https://github.com/mhogg/pyvct",
    download_url = "https://github.com/mhogg/pyvct/releases", 
    packages = ['','pyvct'],
    package_data = {'':['LICENSE.txt','README.md'],'pyvct': ['cythonMods.pyd',]},
    classifiers = [
        "Programming Language :: Python",                                  
        "Programming Language :: Cython",         
        "Programming Language :: Python :: 2",             
        "Programming Language :: Python :: 2.6",                                                    
        "Development Status :: 4 - Beta",                                  
        "Environment :: Other Environment", 
        "Environment :: Plugins", 
        "Intended Audience :: Healthcare Industry",
        "Intended Audience :: Science/Research",   
        "License :: OSI Approved :: MIT License", 
        "Operating System :: OS Independent",     
        "Topic :: Scientific/Engineering :: Medical Science Apps.",
        "Topic :: Scientific/Engineering :: Visualization",
        ],
    ext_modules = ext_modules,
    cmdclass = cmdclass,
    long_description = """ABAQUS plug-in to create virtual CTs from 3D finite element bone/implant models"""
)
