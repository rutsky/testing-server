import sys
from setuptools import setup, find_packages

needs_pytest = {'pytest', 'test'}.intersection(sys.argv)
pytest_runner = ['pytest_runner'] if needs_pytest else []

min_python_info = (3, 5, 0)
if sys.version_info < min_python_info:
    sys.stderr.write(
        "Python at least {} is required, you running {}.\n".format(
            ".".join(map(str, min_python_info)),
            ".".join(map(str, sys.version_info))
        ))
    sys.exit(1)


setup(
    name='testing-server',
    version='0.0.1',
    description="Testing server",
    long_description=open('README.rst').read(),
    package_dir={'': 'src'},
    packages=find_packages('src'),
    setup_requires=[
    ] + pytest_runner,
    tests_require=[
        'pytest',
        'pytest-aiohttp',
        'pytest-logging',
    ],
    test_suite='tests',
    install_requires=[
        'aiohttp',
        'yarl',
        'raven',
        'raven-aiohttp',
    ],
    entry_points={
        'console_scripts': [
            'testing-server=testing_server.scripts.server:main'
        ],
    },
)
