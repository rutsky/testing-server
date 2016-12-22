import pkg_resources
import subprocess


__all__ = ('__version__',)

# All non-development environment should get this version as project version.
# In development environment this version might be used as base for evaluating
# development version.
_version = '0.0.5'
_project_name = 'testing-server'

_git_command = 'git describe --tags --long --dirty'.split()
_dev_version_format = '{tag}.dev{commitcount}+{gitsha}'


# Based on setuptools-git-version implementation
def _format_version(version, fmt=_dev_version_format):
    parts = version.split('-')
    assert len(parts) in (3, 4)
    dirty = len(parts) == 4
    tag, count, sha = parts[:3]
    if count == '0' and not dirty:
        return tag
    return fmt.format(tag=tag, commitcount=count, gitsha=sha.lstrip('g'))


def _get_dev_version():
    try:
        distr = pkg_resources.get_distribution(_project_name)
    except pkg_resources.DistributionNotFound:
        # Project is not installed - project is currently being installed,
        # so we return latest released version.
        return _version

    if not distr.location:
        # Project is installed not in development mode.
        return _version
    else:
        # Project installed in development mode - try to get revision from
        # git.
        try:
            output = subprocess.check_output(_git_command)
        except subprocess.CalledProcessError:
            # Git invocation failed, fallback to latest known version
            return _version

        dev_version = _format_version(output.decode())

        return dev_version


__version__ = _get_dev_version()
