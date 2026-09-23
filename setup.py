from setuptools import find_packages, setup


setup(
    name="matlabgym",
    version="0.4.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    entry_points={"console_scripts": ["matlabgym-demo=matlabgym.demo:main"]},
)
