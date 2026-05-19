from setuptools import setup, find_packages

setup(
    name="zero",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.20.0",
        # Other dependencies...
    ],
    # Other setup configurations...
)