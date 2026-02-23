import os
import re
import subprocess
import sys
from pathlib import Path

import pybind11
from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext
from setuptools.command.develop import develop

PLAT_TO_CMAKE = {
    "win32": "Win32",
    "win-amd64": "x64",
    "win-arm32": "ARM",
    "win-arm64": "ARM64",
}


class CMakeExtension(Extension):
    def __init__(self, name: str, sourcedir: str = "") -> None:
        super().__init__(name, sources=[])
        self.sourcedir = os.fspath(Path(sourcedir).resolve())


class CMakeBuild(build_ext):
    def build_extension(self, ext: CMakeExtension) -> None:
        ext_fullpath = Path.cwd() / self.get_ext_fullpath(ext.name)
        extdir = ext_fullpath.parent.resolve()

        debug = int(os.environ.get("DEBUG", 0)) if self.debug is None else self.debug
        cfg = "Debug" if debug else "Release"

        cmake_generator = os.environ.get("CMAKE_GENERATOR", "")

        cmake_args = [
            f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={extdir}{os.sep}",
            f"-DPYTHON_EXECUTABLE={sys.executable}",
            f"-DCMAKE_BUILD_TYPE={cfg}",
            f"-Dpybind11_DIR={pybind11.get_cmake_dir()}",
        ]
        if "CMAKE_ARGS" in os.environ:
            cmake_args += [item for item in os.environ["CMAKE_ARGS"].split(" ") if item]

        build_args = []
        if self.compiler.compiler_type != "msvc":
            if not cmake_generator or cmake_generator == "Ninja":
                try:
                    import ninja
                    ninja_executable_path = Path(ninja.BIN_DIR) / "ninja"
                    cmake_args += [
                        "-GNinja",
                        f"-DCMAKE_MAKE_PROGRAM:FILEPATH={ninja_executable_path}",
                    ]
                except ImportError:
                    pass
        else:
            single_config = any(x in cmake_generator for x in {"NMake", "Ninja"})
            contains_arch = any(x in cmake_generator for x in {"ARM", "Win64"})
            if not single_config and not contains_arch:
                cmake_args += ["-A", PLAT_TO_CMAKE[self.plat_name]]
            if not single_config:
                cmake_args += [
                    f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_{cfg.upper()}={extdir}"
                ]
            build_args += ["--config", cfg]

        if sys.platform.startswith("darwin"):
            archs = re.findall(r"-arch (\S+)", os.environ.get("ARCHFLAGS", ""))
            if archs:
                cmake_args += ["-DCMAKE_OSX_ARCHITECTURES={}".format(";".join(archs))]

        if "CMAKE_BUILD_PARALLEL_LEVEL" not in os.environ:
            if hasattr(self, "parallel") and self.parallel:
                build_args += [f"-j{self.parallel}"]

        build_temp = Path(self.build_temp) / ext.name
        build_temp.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            ["cmake", ext.sourcedir, *cmake_args], cwd=build_temp, check=True
        )
        subprocess.run(
            ["cmake", "--build", ".", *build_args], cwd=build_temp, check=True
        )


class DevelopNoPipSubprocess(develop):
    """Editable install without calling 'python -m pip' in a subprocess.

    Avoids 'No module named pip' when pip runs this inside a build-isolation env.
    """
    def run(self):
        project_root = Path(__file__).resolve().parent
        # In build-isolation, project is in a temp copy; .pth would point to wrong path
        if "pip-build-env" in str(project_root) or "pip-modern-metadata" in str(project_root):
            print(
                "ERROR: Use editable install without build isolation:\n"
                "  pip install -e \".[telegram]\" --no-build-isolation\n"
                "Install build deps first: pip install cmake pybind11",
                file=sys.stderr,
            )
            sys.exit(1)
        self.initialize_options()
        self.finalize_options()
        # Build extension in-place so duckclaw/_duckclaw*.so lives under project root
        build_ext_cmd = self.distribution.get_command_obj("build_ext")
        build_ext_cmd.inplace = 1
        self.run_command("build_ext")
        # Register editable path: .pth in site-packages pointing at project root
        install_dir = getattr(self, "install_dir", None)
        if install_dir:
            pth_path = Path(install_dir) / "__editable__.duckclaw-0.1.0.pth"
            pth_path.parent.mkdir(parents=True, exist_ok=True)
            pth_path.write_text(str(project_root) + "\n", encoding="utf-8")
        # Skip parent run() so we never call subprocess pip


setup(
    name="duckclaw",
    version="0.1.0",
    description="High-performance C++ analytical memory layer for sovereign AI agents.",
    ext_modules=[CMakeExtension("duckclaw._duckclaw", sourcedir=Path(__file__).parent)],
    cmdclass={"build_ext": CMakeBuild, "develop": DevelopNoPipSubprocess},
    packages=find_packages(include=["duckclaw", "duckclaw.*"]),
    zip_safe=False,
    python_requires=">=3.9",
)
