"""Easy install Tests
"""

import sys
import os
import tempfile
import site
import tarfile
import logging
import itertools
import distutils.errors
import io
import zipfile
import mock
import time
import re
import subprocess
import pathlib
import warnings
import collections

import pytest

import setuptools.command.easy_install as ei
from setuptools.command.easy_install import (
    EasyInstallDeprecationWarning, ScriptWriter, PthDistributions,
    WindowsScriptWriter,
)
from setuptools.dist import Distribution
from pkg_resources import normalize_path
from pkg_resources import Distribution as PRDistribution
from setuptools.tests.server import MockServer
import pkg_resources

from . import contexts
from .textwrap import DALS


@pytest.fixture(autouse=True)
def pip_disable_index(monkeypatch):
    """
    Important: Disable the default index for pip to avoid
    querying packages in the index and potentially resolving
    and installing packages there.
    """
    monkeypatch.setenv('PIP_NO_INDEX', 'true')


class FakeDist:
    def get_entry_map(self, group):
        if group != 'console_scripts':
            return {}
        return {str('name'): 'ep'}

    def as_requirement(self):
        return 'spec'


SETUP_PY = DALS("""
    from setuptools import setup

    setup()
    """)


class TestEasyInstallTest:
    def test_get_script_args(self):
        header = ei.CommandSpec.best().from_environment().as_header()
        dist = FakeDist()
        args = next(ei.ScriptWriter.get_args(dist))
        name, script = itertools.islice(args, 2)
        assert script.startswith(header)
        assert "'spec'" in script
        assert "'console_scripts'" in script
        assert "'name'" in script
        assert re.search(
            '^# EASY-INSTALL-ENTRY-SCRIPT', script, flags=re.MULTILINE)

    def test_no_find_links(self):
        # new option '--no-find-links', that blocks find-links added at
        # the project level
        dist = Distribution()
        cmd = ei.easy_install(dist)
        cmd.check_pth_processing = lambda: True
        cmd.no_find_links = True
        cmd.find_links = ['link1', 'link2']
        cmd.install_dir = os.path.join(tempfile.mkdtemp(), 'ok')
        cmd.args = ['ok']
        cmd.ensure_finalized()
        assert cmd.package_index.scanned_urls == {}

        # let's try without it (default behavior)
        cmd = ei.easy_install(dist)
        cmd.check_pth_processing = lambda: True
        cmd.find_links = ['link1', 'link2']
        cmd.install_dir = os.path.join(tempfile.mkdtemp(), 'ok')
        cmd.args = ['ok']
        cmd.ensure_finalized()
        keys = sorted(cmd.package_index.scanned_urls.keys())
        assert keys == ['link1', 'link2']

    def test_write_exception(self):
        """
        Test that `cant_write_to_target` is rendered as a DistutilsError.
        """
        dist = Distribution()
        cmd = ei.easy_install(dist)
        cmd.install_dir = os.getcwd()
        with pytest.raises(distutils.errors.DistutilsError):
            cmd.cant_write_to_target()

    def test_all_site_dirs(self, monkeypatch):
        """
        get_site_dirs should always return site dirs reported by
        site.getsitepackages.
        """
        path = normalize_path('/setuptools/test/site-packages')

        def mock_gsp():
            return [path]
        monkeypatch.setattr(site, 'getsitepackages', mock_gsp, raising=False)
        assert path in ei.get_site_dirs()

    def test_all_site_dirs_works_without_getsitepackages(self, monkeypatch):
        monkeypatch.delattr(site, 'getsitepackages', raising=False)
        assert ei.get_site_dirs()

    @pytest.fixture
    def sdist_unicode(self, tmpdir):
        files = [
            (
                'setup.py',
                DALS("""
                    import setuptools
                    setuptools.setup(
                        name="setuptools-test-unicode",
                        version="1.0",
                        packages=["mypkg"],
                        include_package_data=True,
                    )
                    """),
            ),
            (
                'mypkg/__init__.py',
                "",
            ),
            (
                'mypkg/☃.txt',
                "",
            ),
        ]
        sdist_name = 'setuptools-test-unicode-1.0.zip'
        sdist = tmpdir / sdist_name
        # can't use make_sdist, because the issue only occurs
        #  with zip sdists.
        sdist_zip = zipfile.ZipFile(str(sdist), 'w')
        for filename, content in files:
            sdist_zip.writestr(filename, content)
        sdist_zip.close()
        return str(sdist)

    @pytest.fixture
    def sdist_unicode_in_script(self, tmpdir):
        files = [
            (
                "setup.py",
                DALS("""
                    import setuptools
                    setuptools.setup(
                        name="setuptools-test-unicode",
                        version="1.0",
                        packages=["mypkg"],
                        include_package_data=True,
                        scripts=['mypkg/unicode_in_script'],
                    )
                    """),
            ),
            ("mypkg/__init__.py", ""),
            (
                "mypkg/unicode_in_script",
                DALS(
                    """
                    #!/bin/sh
                    # á

                    non_python_fn() {
                    }
                """),
            ),
        ]
        sdist_name = "setuptools-test-unicode-script-1.0.zip"
        sdist = tmpdir / sdist_name
        # can't use make_sdist, because the issue only occurs
        #  with zip sdists.
        sdist_zip = zipfile.ZipFile(str(sdist), "w")
        for filename, content in files:
            sdist_zip.writestr(filename, content.encode('utf-8'))
        sdist_zip.close()
        return str(sdist)

    @pytest.fixture
    def sdist_script(self, tmpdir):
        files = [
            (
                'setup.py',
                DALS("""
                    import setuptools
                    setuptools.setup(
                        name="setuptools-test-script",
                        version="1.0",
                        scripts=["mypkg_script"],
                    )
                    """),
            ),
            (
                'mypkg_script',
                DALS("""
                     #/usr/bin/python
                     print('mypkg_script')
                     """),
            ),
        ]
        sdist_name = 'setuptools-test-script-1.0.zip'
        sdist = str(tmpdir / sdist_name)
        make_sdist(sdist, files)
        return sdist

    def test_dist_get_script_args_deprecated(self):
        with pytest.warns(EasyInstallDeprecationWarning):
            ScriptWriter.get_script_args(None, None)

    def test_dist_get_script_header_deprecated(self):
        with pytest.warns(EasyInstallDeprecationWarning):
            ScriptWriter.get_script_header("")

    def test_dist_get_writer_deprecated(self):
        with pytest.warns(EasyInstallDeprecationWarning):
            ScriptWriter.get_writer(None)

    def test_dist_WindowsScriptWriter_get_writer_deprecated(self):
        with pytest.warns(EasyInstallDeprecationWarning):
            WindowsScriptWriter.get_writer()


@pytest.mark.filterwarnings('ignore:Unbuilt egg')
class TestPTHFileWriter:
    def test_add_from_cwd_site_sets_dirty(self):
        '''a pth file manager should set dirty
        if a distribution is in site but also the cwd
        '''
        pth = PthDistributions('does-not_exist', [os.getcwd()])
        assert not pth.dirty
        pth.add(PRDistribution(os.getcwd()))
        assert pth.dirty

    def test_add_from_site_is_ignored(self):
        location = '/test/location/does-not-have-to-exist'
        # PthDistributions expects all locations to be normalized
        location = pkg_resources.normalize_path(location)
        pth = PthDistributions('does-not_exist', [location, ])
        assert not pth.dirty
        pth.add(PRDistribution(location))
        assert not pth.dirty


@pytest.fixture
def setup_context(tmpdir):
    with (tmpdir / 'setup.py').open('w') as f:
        f.write(SETUP_PY)
    with tmpdir.as_cwd():
        yield tmpdir


@pytest.mark.usefixtures("user_override")
@pytest.mark.usefixtures("setup_context")
class TestUserInstallTest:

    # prevent check that site-packages is writable. easy_install
    # shouldn't be writing to system site-packages during finalize
    # options, but while it does, bypass the behavior.
    prev_sp_write = mock.patch(
        'setuptools.command.easy_install.easy_install.check_site_dir',
        mock.Mock(),
    )

    # simulate setuptools installed in user site packages
    @mock.patch('setuptools.command.easy_install.__file__', site.USER_SITE)
    @mock.patch('site.ENABLE_USER_SITE', True)
    @prev_sp_write
    def test_user_install_not_implied_user_site_enabled(self):
        self.assert_not_user_site()

    @mock.patch('site.ENABLE_USER_SITE', False)
    @prev_sp_write
    def test_user_install_not_implied_user_site_disabled(self):
        self.assert_not_user_site()

    @staticmethod
    def assert_not_user_site():
        # create a finalized easy_install command
        dist = Distribution()
        dist.script_name = 'setup.py'
        cmd = ei.easy_install(dist)
        cmd.args = ['py']
        cmd.ensure_finalized()
        assert not cmd.user, 'user should not be implied'

    def test_multiproc_atexit(self):
        pytest.importorskip('multiprocessing')

        log = logging.getLogger('test_easy_install')
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
        log.info('this should not break')

    @pytest.fixture()
    def foo_package(self, tmpdir):
        egg_file = tmpdir / 'foo-1.0.egg-info'
        with egg_file.open('w') as f:
            f.write('Name: foo\n')
        return str(tmpdir)

    @pytest.fixture()
    def install_target(self, tmpdir):
        target = str(tmpdir)
        with mock.patch('sys.path', sys.path + [target]):
            python_path = os.path.pathsep.join(sys.path)
            with mock.patch.dict(os.environ, PYTHONPATH=python_path):
                yield target

    def test_local_index(self, foo_package, install_target):
        """
        The local index must be used when easy_install locates installed
        packages.
        """
        dist = Distribution()
        dist.script_name = 'setup.py'
        cmd = ei.easy_install(dist)
        cmd.install_dir = install_target
        cmd.args = ['foo']
        cmd.ensure_finalized()
        cmd.local_index.scan([foo_package])
        res = cmd.easy_install('foo')
        actual = os.path.normcase(os.path.realpath(res.location))
        expected = os.path.normcase(os.path.realpath(foo_package))
        assert actual == expected


@pytest.fixture
def distutils_package():
    distutils_setup_py = SETUP_PY.replace(
        'from setuptools import setup',
        'from distutils.core import setup',
    )
    with contexts.tempdir(cd=os.chdir):
        with open('setup.py', 'w') as f:
            f.write(distutils_setup_py)
        yield


@pytest.fixture
def mock_index():
    # set up a server which will simulate an alternate package index.
    p_index = MockServer()
    if p_index.server_port == 0:
        # Some platforms (Jython) don't find a port to which to bind,
        # so skip test for them.
        pytest.skip("could not find a valid port")
    p_index.start()
    return p_index


class TestInstallRequires:
    def test_setup_install_includes_dependencies(self, tmp_path, mock_index):
        """
        When ``python setup.py install`` is called directly, it will use easy_install
        to fetch dependencies.
        """
        # TODO: Remove these tests once `setup.py install` is completely removed
        project_root = tmp_path / "project"
        project_root.mkdir(exist_ok=True)
        install_root = tmp_path / "install"
        install_root.mkdir(exist_ok=True)

        self.create_project(project_root)
        cmd = [
            sys.executable,
            '-c', '__import__("setuptools").setup()',
            'install',
            '--install-base', str(install_root),
            '--install-lib', str(install_root),
            '--install-headers', str(install_root),
            '--install-scripts', str(install_root),
            '--install-data', str(install_root),
            '--install-purelib', str(install_root),
            '--install-platlib', str(install_root),
        ]
        env = {"PYTHONPATH": str(install_root), "__EASYINSTALL_INDEX": mock_index.url}
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            subprocess.check_output(
                cmd, cwd=str(project_root), env=env, stderr=subprocess.STDOUT, text=True
            )
        try:
            assert '/does-not-exist/' in {r.path for r in mock_index.requests}
            assert next(
                line
                for line in exc_info.value.output.splitlines()
                if "not find suitable distribution for" in line
                and "does-not-exist" in line
            )
        except Exception:
            if "failed to get random numbers" in exc_info.value.output:
                pytest.xfail(f"{sys.platform} failure - {exc_info.value.output}")
            raise

    def create_project(self, root):
        config = """
        [metadata]
        name = project
        version = 42

        [options]
        install_requires = does-not-exist
        py_modules = mod
        """
        (root / 'setup.cfg').write_text(DALS(config), encoding="utf-8")
        (root / 'mod.py').touch()


def make_trivial_sdist(dist_path, distname, version):
    """
    Create a simple sdist tarball at dist_path, containing just a simple
    setup.py.
    """

    make_sdist(dist_path, [
        ('setup.py',
         DALS("""\
             import setuptools
             setuptools.setup(
                 name=%r,
                 version=%r
             )
         """ % (distname, version))),
        ('setup.cfg', ''),
    ])


def make_nspkg_sdist(dist_path, distname, version):
    """
    Make an sdist tarball with distname and version which also contains one
    package with the same name as distname.  The top-level package is
    designated a namespace package).
    """

    parts = distname.split('.')
    nspackage = parts[0]

    packages = ['.'.join(parts[:idx]) for idx in range(1, len(parts) + 1)]

    setup_py = DALS("""\
        import setuptools
        setuptools.setup(
            name=%r,
            version=%r,
            packages=%r,
            namespace_packages=[%r]
        )
    """ % (distname, version, packages, nspackage))

    init = "__import__('pkg_resources').declare_namespace(__name__)"

    files = [('setup.py', setup_py),
             (os.path.join(nspackage, '__init__.py'), init)]
    for package in packages[1:]:
        filename = os.path.join(*(package.split('.') + ['__init__.py']))
        files.append((filename, ''))

    make_sdist(dist_path, files)


def make_python_requires_sdist(dist_path, distname, version, python_requires):
    make_sdist(dist_path, [
        (
            'setup.py',
            DALS("""\
                import setuptools
                setuptools.setup(
                  name={name!r},
                  version={version!r},
                  python_requires={python_requires!r},
                )
                """).format(
                name=distname, version=version,
                python_requires=python_requires)),
        ('setup.cfg', ''),
    ])


def make_sdist(dist_path, files):
    """
    Create a simple sdist tarball at dist_path, containing the files
    listed in ``files`` as ``(filename, content)`` tuples.
    """

    # Distributions with only one file don't play well with pip.
    assert len(files) > 1
    with tarfile.open(dist_path, 'w:gz') as dist:
        for filename, content in files:
            file_bytes = io.BytesIO(content.encode('utf-8'))
            file_info = tarfile.TarInfo(name=filename)
            file_info.size = len(file_bytes.getvalue())
            file_info.mtime = int(time.time())
            dist.addfile(file_info, fileobj=file_bytes)


def create_setup_requires_package(path, distname='foobar', version='0.1',
                                  make_package=make_trivial_sdist,
                                  setup_py_template=None, setup_attrs={},
                                  use_setup_cfg=()):
    """Creates a source tree under path for a trivial test package that has a
    single requirement in setup_requires--a tarball for that requirement is
    also created and added to the dependency_links argument.

    ``distname`` and ``version`` refer to the name/version of the package that
    the test package requires via ``setup_requires``.  The name of the test
    package itself is just 'test_pkg'.
    """

    test_setup_attrs = {
        'name': 'test_pkg', 'version': '0.0',
        'setup_requires': ['%s==%s' % (distname, version)],
        'dependency_links': [os.path.abspath(path)]
    }
    test_setup_attrs.update(setup_attrs)

    test_pkg = os.path.join(path, 'test_pkg')
    os.mkdir(test_pkg)

    # setup.cfg
    if use_setup_cfg:
        options = []
        metadata = []
        for name in use_setup_cfg:
            value = test_setup_attrs.pop(name)
            if name in 'name version'.split():
                section = metadata
            else:
                section = options
            if isinstance(value, (tuple, list)):
                value = ';'.join(value)
            section.append('%s: %s' % (name, value))
        test_setup_cfg_contents = DALS(
            """
            [metadata]
            {metadata}
            [options]
            {options}
            """
        ).format(
            options='\n'.join(options),
            metadata='\n'.join(metadata),
        )
    else:
        test_setup_cfg_contents = ''
    with open(os.path.join(test_pkg, 'setup.cfg'), 'w') as f:
        f.write(test_setup_cfg_contents)

    # setup.py
    if setup_py_template is None:
        setup_py_template = DALS("""\
            import setuptools
            setuptools.setup(**%r)
        """)
    with open(os.path.join(test_pkg, 'setup.py'), 'w') as f:
        f.write(setup_py_template % test_setup_attrs)

    foobar_path = os.path.join(path, '%s-%s.tar.gz' % (distname, version))
    make_package(foobar_path, distname, version)

    return test_pkg


@pytest.mark.skipif(
    sys.platform.startswith('java') and ei.is_sh(sys.executable),
    reason="Test cannot run under java when executable is sh"
)
class TestScriptHeader:
    non_ascii_exe = '/Users/José/bin/python'
    exe_with_spaces = r'C:\Program Files\Python36\python.exe'

    def test_get_script_header(self):
        expected = '#!%s\n' % ei.nt_quote_arg(os.path.normpath(sys.executable))
        actual = ei.ScriptWriter.get_header('#!/usr/local/bin/python')
        assert actual == expected

    def test_get_script_header_args(self):
        expected = '#!%s -x\n' % ei.nt_quote_arg(
            os.path.normpath(sys.executable))
        actual = ei.ScriptWriter.get_header('#!/usr/bin/python -x')
        assert actual == expected

    def test_get_script_header_non_ascii_exe(self):
        actual = ei.ScriptWriter.get_header(
            '#!/usr/bin/python',
            executable=self.non_ascii_exe)
        expected = str('#!%s -x\n') % self.non_ascii_exe
        assert actual == expected

    def test_get_script_header_exe_with_spaces(self):
        actual = ei.ScriptWriter.get_header(
            '#!/usr/bin/python',
            executable='"' + self.exe_with_spaces + '"')
        expected = '#!"%s"\n' % self.exe_with_spaces
        assert actual == expected


class TestCommandSpec:
    def test_custom_launch_command(self):
        """
        Show how a custom CommandSpec could be used to specify a #! executable
        which takes parameters.
        """
        cmd = ei.CommandSpec(['/usr/bin/env', 'python3'])
        assert cmd.as_header() == '#!/usr/bin/env python3\n'

    def test_from_param_for_CommandSpec_is_passthrough(self):
        """
        from_param should return an instance of a CommandSpec
        """
        cmd = ei.CommandSpec(['python'])
        cmd_new = ei.CommandSpec.from_param(cmd)
        assert cmd is cmd_new

    @mock.patch('sys.executable', TestScriptHeader.exe_with_spaces)
    @mock.patch.dict(os.environ)
    def test_from_environment_with_spaces_in_executable(self):
        os.environ.pop('__PYVENV_LAUNCHER__', None)
        cmd = ei.CommandSpec.from_environment()
        assert len(cmd) == 1
        assert cmd.as_header().startswith('#!"')

    def test_from_simple_string_uses_shlex(self):
        """
        In order to support `executable = /usr/bin/env my-python`, make sure
        from_param invokes shlex on that input.
        """
        cmd = ei.CommandSpec.from_param('/usr/bin/env my-python')
        assert len(cmd) == 2
        assert '"' not in cmd.as_header()


class TestWindowsScriptWriter:
    def test_header(self):
        hdr = ei.WindowsScriptWriter.get_header('')
        assert hdr.startswith('#!')
        assert hdr.endswith('\n')
        hdr = hdr.lstrip('#!')
        hdr = hdr.rstrip('\n')
        # header should not start with an escaped quote
        assert not hdr.startswith('\\"')


VersionStub = collections.namedtuple(
    "VersionStub", "major, minor, micro, releaselevel, serial")


def test_use_correct_python_version_string(tmpdir, tmpdir_cwd, monkeypatch):
    # In issue #3001, easy_install wrongly uses the `python3.1` directory
    # when the interpreter is `python3.10` and the `--user` option is given.
    # See pypa/setuptools#3001.
    dist = Distribution()
    cmd = dist.get_command_obj('easy_install')
    cmd.args = ['ok']
    cmd.optimize = 0
    cmd.user = True
    cmd.install_userbase = str(tmpdir)
    cmd.install_usersite = None
    install_cmd = dist.get_command_obj('install')
    install_cmd.install_userbase = str(tmpdir)
    install_cmd.install_usersite = None

    with monkeypatch.context() as patch, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        version = '3.10.1 (main, Dec 21 2021, 09:17:12) [GCC 10.2.1 20210110]'
        info = VersionStub(3, 10, 1, "final", 0)
        patch.setattr('site.ENABLE_USER_SITE', True)
        patch.setattr('sys.version', version)
        patch.setattr('sys.version_info', info)
        patch.setattr(cmd, 'create_home_path', mock.Mock())
        cmd.finalize_options()

    name = "pypy" if hasattr(sys, 'pypy_version_info') else "python"
    install_dir = cmd.install_dir.lower()

    # In some platforms (e.g. Windows), install_dir is mostly determined
    # via `sysconfig`, which define constants eagerly at module creation.
    # This means that monkeypatching `sys.version` to emulate 3.10 for testing
    # may have no effect.
    # The safest test here is to rely on the fact that 3.1 is no longer
    # supported/tested, and make sure that if 'python3.1' ever appears in the string
    # it is followed by another digit (e.g. 'python3.10').
    if re.search(name + r'3\.?1', install_dir):
        assert re.search(name + r'3\.?1\d', install_dir)

    # The following "variables" are used for interpolation in distutils
    # installation schemes, so it should be fair to treat them as "semi-public",
    # or at least public enough so we can have a test to make sure they are correct
    assert cmd.config_vars['py_version'] == '3.10.1'
    assert cmd.config_vars['py_version_short'] == '3.10'
    assert cmd.config_vars['py_version_nodot'] == '310'


def test_editable_user_and_build_isolation(setup_context, monkeypatch, tmp_path):
    ''' `setup.py develop` should honor `--user` even under build isolation'''

    # == Arrange ==
    # Pretend that build isolation was enabled
    # e.g pip sets the environment varible PYTHONNOUSERSITE=1
    monkeypatch.setattr('site.ENABLE_USER_SITE', False)

    # Patching $HOME for 2 reasons:
    # 1. setuptools/command/easy_install.py:create_home_path
    #    tries creating directories in $HOME
    # given `self.config_vars['DESTDIRS'] = "/home/user/.pyenv/versions/3.9.10 /home/user/.pyenv/versions/3.9.10/lib /home/user/.pyenv/versions/3.9.10/lib/python3.9 /home/user/.pyenv/versions/3.9.10/lib/python3.9/lib-dynload"``  # noqa: E501
    # it will `makedirs("/home/user/.pyenv/versions/3.9.10 /home/user/.pyenv/versions/3.9.10/lib /home/user/.pyenv/versions/3.9.10/lib/python3.9 /home/user/.pyenv/versions/3.9.10/lib/python3.9/lib-dynload")``  # noqa: E501
    # 2. We are going to force `site` to update site.USER_BASE and site.USER_SITE
    #    To point inside our new home
    monkeypatch.setenv('HOME', str(tmp_path / '.home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / '.home'))
    monkeypatch.setenv('APPDATA', str(tmp_path / '.home'))
    monkeypatch.setattr('site.USER_BASE', None)
    monkeypatch.setattr('site.USER_SITE', None)
    user_site = pathlib.Path(site.getusersitepackages())
    user_site.mkdir(parents=True, exist_ok=True)

    sys_prefix = (tmp_path / '.sys_prefix')
    sys_prefix.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr('sys.prefix', str(sys_prefix))

    setup_script = (
        "__import__('setuptools').setup(name='aproj', version=42, packages=[])\n"
    )
    (tmp_path / "setup.py").write_text(setup_script, encoding="utf-8")

    # == Sanity check ==
    assert list(sys_prefix.glob("*")) == []
    assert list(user_site.glob("*")) == []

    # == Act ==
    run_setup('setup.py', ['develop', '--user'])

    # == Assert ==
    # Should not install to sys.prefix
    assert list(sys_prefix.glob("*")) == []
    # Should install to user site
    installed = {f.name for f in user_site.glob("*")}
    # sometimes easy-install.pth is created and sometimes not
    installed = installed - {"easy-install.pth"}
    assert installed == {'aproj.egg-link'}
