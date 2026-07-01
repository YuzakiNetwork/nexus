from setuptools import find_packages, setup


setup(
    name="nexus-cli",
    version="0.2.0",
    description="Terminal coding agent powered by NVIDIA API.",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
    ],
    entry_points={
        "console_scripts": [
            "nexus=nexus_cli.agent:main",
        ],
    },
    python_requires=">=3.10",
)
