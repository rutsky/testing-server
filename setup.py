import sys
import os
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


def read_file(filename):
    abs_path = os.path.join(os.path.dirname(__file__), filename)
    with open(abs_path, encoding='utf-8') as f:
        return f.read()

about = {}
exec(read_file(os.path.join('src', 'testing_server', '__about__.py')), about)

tests_deps = [
    'pytest',
    'pytest-aiohttp',
    'pytest-logging',
]

setup(
    name='testing-server',
    version=about['__version__'],
    description="Testing server",
    long_description=read_file('README.rst'),
    package_dir={'': 'src'},
    packages=find_packages('src'),
    setup_requires=[
    ] + pytest_runner,
    tests_require=tests_deps,
    test_suite='tests',
    install_requires=[
        'aiohttp',
        'aiohttp-cors',
        'async-timeout',
        'passlib',
        'pyjwt',
        'raven',
        'raven-aiohttp',
        'yarl',
    ],
    extras_require={
        'test': tests_deps
    },
    entry_points={
        'console_scripts': [
            'testing-server=testing_server.scripts.server:main'
        ],
    },
)
