import uuid

from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    reqs = [
        r
        for r in f.read().splitlines()
        if (len(r) > 0 and not (r.startswith("#") or r.startswith("git+")))
    ]

setup(
    name="pyfg",
    version="0.52",
    packages=find_packages(),
    author="XNET",
    author_email="lindblom+pyfg@spotify.com",
    description="Python API for fortigate",
    url="https://github.com/spotify/pyfg",
    include_package_data=True,
    install_requires=reqs
)
