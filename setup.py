from setuptools import find_packages, setup


setup(
    name='jooce',
    version="0.0.1",
    url='https://github.com/kurtiss/jooce',
    author='Kurtiss Hare',
    author_email='kurtiss@gmail.com',
    license='proprietary',
    packages=find_packages(),
    install_requires=[
        'aiocontextvars;python_version<"3.7"',
    ],
    extras_require={
        'dev': [
            'pycodestyle',
            'pytest',
        ]
    },
    package_data={},
    entry_points={},
)
