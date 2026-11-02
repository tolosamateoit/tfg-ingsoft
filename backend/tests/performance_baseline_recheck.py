"""Explicit diagnostic: recheck existing failures against HEAD, only in local PG.

Run via tests.run_postgresql_local tests.performance_baseline_recheck.
Original application modules are loaded in memory; no checkout or files changed.
Not part of automatic test discovery.
"""
import importlib.abc
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


class HeadApplication(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'app' and not fullname.startswith('app.'):
            return None
        relative = 'backend/' + fullname.replace('.', '/')
        package = (ROOT / relative).is_dir()
        filename = relative + ('/__init__.py' if package else '.py')
        if not (ROOT / filename).exists():
            return None
        spec = importlib.util.spec_from_loader(fullname, self, is_package=package)
        spec.loader_state = filename
        return spec

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename = module.__spec__.loader_state
        module.__file__ = str(ROOT / filename)
        if module.__spec__.submodule_search_locations is not None:
            module.__path__ = [str((ROOT / filename).parent)]
        source = subprocess.check_output(['git', 'show', 'HEAD:' + filename], cwd=ROOT)
        exec(compile(source, module.__file__, 'exec'), module.__dict__)


sys.meta_path.insert(0, HeadApplication())

# También permite medir las mismas escrituras con el código anterior:
# tests.run_postgresql_local tests.performance_baseline_recheck.WritePerformanceTests
from tests.test_performance_postgresql import WritePerformanceTests


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames([
        'tests.test_auth.AuthApiTests.test_only_approved_routes_are_published',
        'tests.test_auth_api_postgresql.AuthApiPostgreSQLTests.test_only_approved_routes_are_published',
        'tests.test_demo_history_postgresql.HistoricalPostgreSQLTests.test_real_motors_and_hu04_use_the_history_without_persisting_results',
        'tests.test_experiment_logistics_postgresql.ExperimentalLogisticsTests.test_formula_ties_ranking_assignment_and_rounding',
    ])
