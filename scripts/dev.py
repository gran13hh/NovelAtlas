"""Start and stop the NovelAtlas API and web development servers together."""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "apps" / "web"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


@dataclass(frozen=True, slots=True)
class ServerProcess:
    """A named development server process."""

    name: str
    process: subprocess.Popen[bytes]


class StartupError(RuntimeError):
    """Raised when prerequisites or a development server are unavailable."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the NovelAtlas FastAPI and Vite development servers.",
    )
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser after both servers are ready.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check prerequisites without starting either server.",
    )
    return parser.parse_args()


def check_prerequisites() -> str:
    """Validate local Python and frontend dependencies."""

    if not VENV_PYTHON.is_file():
        raise StartupError("未找到项目虚拟环境：请先创建并安装 .venv")
    if not (WEB_ROOT / "package.json").is_file():
        raise StartupError("未找到前端 package.json")
    if not (WEB_ROOT / "node_modules").is_dir():
        raise StartupError("前端依赖尚未安装：请在 apps/web 执行 npm install")

    npm = shutil.which("npm")
    if npm is None:
        raise StartupError("未找到 npm，请确认 Node.js 已安装并位于 PATH")

    dependency_check = subprocess.run(
        [
            str(VENV_PYTHON),
            "-c",
            "import fastapi, uvicorn; print('Python dependencies: OK')",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if dependency_check.returncode != 0:
        raise StartupError(
            "Python 依赖不完整，请执行：.venv/bin/python -m pip install -r requirements.txt"
        )
    return npm


def start_servers(npm: str, api_port: int, web_port: int) -> list[ServerProcess]:
    """Start both development servers in independent process groups."""

    backend = subprocess.Popen(
        [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "apps.api.novelatlas_api.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        cwd=PROJECT_ROOT,
        start_new_session=True,
    )
    frontend = subprocess.Popen(
        [
            npm,
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(web_port),
            "--strictPort",
        ],
        cwd=WEB_ROOT,
        start_new_session=True,
    )
    return [
        ServerProcess(name="FastAPI", process=backend),
        ServerProcess(name="Vite", process=frontend),
    ]


def wait_for_url(
    url: str,
    servers: list[ServerProcess],
    *,
    timeout_seconds: float = 30,
) -> None:
    """Wait for a URL while failing quickly if a server exits."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for server in servers:
            return_code = server.process.poll()
            if return_code is not None:
                raise StartupError(
                    f"{server.name} 启动失败，退出码为 {return_code}"
                )

        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)

    raise StartupError(f"等待服务超时：{url}")


def stop_servers(servers: list[ServerProcess]) -> None:
    """Terminate both process groups, then force-stop stragglers."""

    for server in servers:
        if server.process.poll() is None:
            try:
                os.killpg(server.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(server.process.poll() is not None for server in servers):
            return
        time.sleep(0.1)

    for server in servers:
        if server.process.poll() is None:
            try:
                os.killpg(server.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def monitor_servers(servers: list[ServerProcess]) -> None:
    """Keep the launcher alive until the user stops it or a server exits."""

    while True:
        for server in servers:
            return_code = server.process.poll()
            if return_code is not None:
                raise StartupError(
                    f"{server.name} 已意外退出，退出码为 {return_code}"
                )
        time.sleep(0.5)


def install_signal_handlers() -> None:
    """Convert terminal close signals into normal coordinated shutdown."""

    def handle_shutdown_signal(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, handle_shutdown_signal)


def main() -> int:
    args = parse_args()
    servers: list[ServerProcess] = []

    try:
        npm = check_prerequisites()
        print("✓ Python 与 npm 环境检查通过", flush=True)
        if args.check:
            return 0

        install_signal_handlers()
        print("正在启动 NovelAtlas 前后端…", flush=True)
        servers = start_servers(npm, args.api_port, args.web_port)

        api_url = f"http://127.0.0.1:{args.api_port}/api/health"
        web_url = f"http://127.0.0.1:{args.web_port}"
        wait_for_url(api_url, servers)
        wait_for_url(web_url, servers)

        print(flush=True)
        print(f"✓ API：{api_url}", flush=True)
        print(f"✓ Web：{web_url}", flush=True)
        print("按 Ctrl+C 可同时关闭前后端。", flush=True)
        if not args.no_open:
            webbrowser.open_new_tab(web_url)

        monitor_servers(servers)
    except KeyboardInterrupt:
        print("\n正在关闭 NovelAtlas…", flush=True)
    except StartupError as error:
        print(f"\n启动失败：{error}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop_servers(servers)

    print("✓ 前后端已关闭", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
