import ast
import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

ROOT = Path(__file__).resolve().parents[1]


def _absolute_internal_imports(path: Path):
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (
                node.level == 0
                and node.module
                and node.module.split(".")[0] == "dialoguesoul"
            ):
                yield path, node.lineno, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "dialoguesoul":
                    yield path, node.lineno, alias.name


class PackageImportTest(unittest.TestCase):
    def test_no_absolute_internal_imports_remain(self):
        files = [ROOT / "main.py", *sorted((ROOT / "dialoguesoul").rglob("*.py"))]
        offenders = sorted(
            f"{path.relative_to(ROOT)}:{line} {module}"
            for path in files
            for _, line, module in _absolute_internal_imports(path)
        )
        self.assertEqual(offenders, [])

    def test_package_module_imports(self):
        module = importlib.import_module("dialoguesoul.plugin")
        self.assertTrue(hasattr(module, "DialoguesSoulPlugin"))

    def test_main_loads_under_astrbot_plugin_package(self):
        root = ROOT
        for name in ("data", "data.plugins"):
            package = sys.modules.get(name)
            if package is None:
                package = types.ModuleType(name)
                package.__path__ = []
                sys.modules[name] = package

        package_name = "data.plugins.astrbot_plugin_dialoguesoul"
        package = types.ModuleType(package_name)
        package.__path__ = [str(root)]
        sys.modules[package_name] = package

        module_name = f"{package_name}.main"
        spec = importlib.util.spec_from_file_location(module_name, root / "main.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        self.assertTrue(hasattr(module, "DialoguesSoul"))
        self.assertTrue(module.__name__.endswith(".main"))


if __name__ == "__main__":
    unittest.main()
