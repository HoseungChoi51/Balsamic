"""A coding workspace starts from the package caches and installed packages of the newest earlier workspace on the same
dependencies, so a similar problem does not download and install them again."""
import os

from optimization_framework.agents.development_runtime import DockerWorkspace, dependency_names


def pyproject(*dependencies):
    return ("[project]\nname = 'x'\nversion = '0.1.0'\ndependencies = [" + ", ".join(repr(item) for item in dependencies) + "]\n").encode()


def earlier(directory, name, dependencies, mtime):
    root = directory / name
    (root / "home/.cache/uv").mkdir(parents=True)
    (root / "home/.cache/uv/wheel").write_text(name)
    (root / "home/.local/lib/python3.12/site-packages").mkdir(parents=True)
    (root / "home/.local/share/code-server").mkdir(parents=True)
    (root / "home/.pi/agent").mkdir(parents=True)
    (root / "home/.pi/agent/auth.json").write_text("secret")
    (root / "work/repo/libraries/other").mkdir(parents=True)
    (root / "work/repo/libraries/other/pyproject.toml").write_bytes(pyproject(*dependencies))
    os.utime(root / "home", (mtime, mtime))
    return root


def test_dependency_names_ignore_versions_extras_and_case():
    assert dependency_names(pyproject("NumPy>=2.4.2,<3", "pytest_cov[toml]==1", "uv ; python_version > '3'")) == {"numpy", "pytest-cov", "uv"}
    assert dependency_names(b"not toml [") == frozenset() and dependency_names(None) == frozenset()


def test_a_new_workspace_takes_the_newest_home_on_the_same_dependencies_and_nothing_private(tmp_path):
    earlier(tmp_path, "development_old", ["numpy==2.4.2"], 1000)
    earlier(tmp_path, "development_new", ["numpy>=2.4"], 2000)
    earlier(tmp_path, "development_other", ["numpy", "scipy"], 3000)
    root = tmp_path / "development_next"
    (root / "home").mkdir(parents=True)
    assert DockerWorkspace(tmp_path).warm(root, {"files": {"pyproject.toml": pyproject("numpy")}}) == "development_new"
    assert (root / "home/.cache/uv/wheel").read_text() == "development_new" and (root / "home/.local/lib/python3.12").is_dir()
    assert (root / "home/.warm_from").read_text() == "development_new"
    assert not (root / "home/.pi").exists() and not (root / "home/.local/share").exists()


def test_no_match_a_recovered_home_and_a_library_without_dependencies_stay_as_they_are(tmp_path):
    earlier(tmp_path, "development_old", ["numpy"], 1000)
    driver = DockerWorkspace(tmp_path)
    fresh = tmp_path / "development_a"
    (fresh / "home").mkdir(parents=True)
    assert driver.warm(fresh, {"files": {"pyproject.toml": pyproject("scipy")}}) is None
    assert driver.warm(fresh, {"files": {"pyproject.toml": pyproject()}}) is None and driver.warm(fresh, None) is None
    recovered = tmp_path / "development_b"
    (recovered / "home/.cache").mkdir(parents=True)
    assert driver.warm(recovered, {"files": {"pyproject.toml": pyproject("numpy")}}) is None
    assert not (recovered / "home/.warm_from").exists()
