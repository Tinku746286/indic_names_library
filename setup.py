from setuptools import setup, find_packages

setup(
    name="indic-places",
    version="1.0.0",
    description="Indian place name identifier with fuzzy (SymSpell-style) lookup",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Tinku",
    url="https://github.com/Tinku746286/indic_names_library",
    license="MIT",
    packages=find_packages(),
    package_data={"indic_places": ["data/*.json"]},
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "indic-places=indic_places.cli:main",
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Text Processing :: Linguistic",
    ],
)
